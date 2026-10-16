#!/usr/bin/env python3
"""CHARMEUR static pages plus the protected partner-management API."""
from __future__ import annotations

import hashlib
import hmac
import os
import time
import uuid
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from flask import Flask, abort, jsonify, make_response, request, send_from_directory
from psycopg.rows import dict_row


ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "5000"))
SESSION_COOKIE = "partner_admin_session"
SESSION_TTL = 12 * 60 * 60
ALLOWED_CATEGORIES = {
    "hair", "grooming", "fashion", "photo", "wellness",
    "whitening", "clinic", "lesson",
}
PARTNER_FIELDS = (
    "id", "name", "category", "area", "description", "website_url",
    "image_url", "nexus_points", "map_x", "map_y", "published",
    "display_order",
)
PUBLIC_PAGES = {
    "index.html", "partners.html", "privacy.html", "terms.html",
    "tokushoho.html", "admin.html",
}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024
login_attempts: dict[str, list[float]] = {}


def db_connection():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(database_url, row_factory=dict_row)


def partner_json(row):
    result = {key: row[key] for key in PARTNER_FIELDS}
    result["id"] = str(result["id"])
    for key in ("map_x", "map_y"):
        if result[key] is not None:
            result[key] = float(result[key])
    return result


def admin_secret():
    return os.environ.get("PARTNER_ADMIN_PASSWORD", "")


def session_signature(expiry: str) -> str:
    secret = os.environ.get("SESSION_SECRET", "")
    if not secret:
        raise RuntimeError("SESSION_SECRET is not configured")
    return hmac.new(secret.encode(), expiry.encode(), hashlib.sha256).hexdigest()


def is_admin():
    token = request.cookies.get(SESSION_COOKIE, "")
    try:
        expiry, signature = token.split(".", 1)
        if int(expiry) < int(time.time()):
            return False
        return hmac.compare_digest(signature, session_signature(expiry))
    except (ValueError, RuntimeError):
        return False


def require_admin(handler):
    @wraps(handler)
    def wrapped(*args, **kwargs):
        if not is_admin():
            return jsonify(error="ログインが必要です。"), 401
        return handler(*args, **kwargs)
    return wrapped


def validate_same_origin():
    origin = request.headers.get("Origin")
    if not origin:
        return
    parsed = urlsplit(origin)
    if parsed.netloc != request.host or parsed.scheme not in ("http", "https"):
        abort(403)


def validate_partner(payload, existing=None):
    if not isinstance(payload, dict):
        return None, "入力内容を確認してください。"
    data = {}
    for field, default, limit in (
        ("name", "", 120),
        ("category", "", 30),
        ("area", "", 120),
        ("description", "", 2000),
        ("website_url", "", 500),
        ("image_url", "", 1000),
    ):
        value = payload.get(field, existing[field] if existing else default)
        if not isinstance(value, str):
            return None, "入力内容を確認してください。"
        value = value.strip()
        if len(value) > limit:
            return None, f"{field}が長すぎます。"
        data[field] = value

    if not data["name"]:
        return None, "提携先名を入力してください。"
    if data["category"] not in ALLOWED_CATEGORIES:
        return None, "カテゴリを選択してください。"

    for field in ("website_url", "image_url"):
        value = data[field]
        if value:
            parsed = urlsplit(value)
            if parsed.scheme != "https" or not parsed.netloc:
                return None, "URLはhttps://から始まる有効なURLを入力してください。"

    try:
        points = payload.get("nexus_points", existing["nexus_points"] if existing else 0)
        points = int(points)
        if points < 0 or points > 1_000_000:
            raise ValueError
        data["nexus_points"] = points
        for field in ("map_x", "map_y"):
            value = payload.get(field, existing[field] if existing else None)
            if value in (None, ""):
                data[field] = None
            else:
                number = float(value)
                if not 0 <= number <= 100:
                    raise ValueError
                data[field] = number
        published = payload.get("published", existing["published"] if existing else False)
        if not isinstance(published, bool):
            raise ValueError
        data["published"] = published
        order = payload.get("display_order", existing["display_order"] if existing else 0)
        data["display_order"] = max(0, min(int(order), 100_000))
    except (TypeError, ValueError):
        return None, "ポイント数、地図位置、公開状態を確認してください。"
    return data, None


@app.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.get("/")
def home():
    return send_from_directory(ROOT, "index.html")


@app.get("/admin")
@app.get("/admin/")
def admin_page():
    return send_from_directory(ROOT, "admin.html")


@app.get("/<path:page>")
def static_page(page):
    if page not in PUBLIC_PAGES:
        abort(404)
    return send_from_directory(ROOT, page)


@app.get("/api/partners")
def get_public_partners():
    with db_connection() as conn:
        rows = conn.execute(
            """SELECT id, name, category, area, description, website_url,
                      image_url, nexus_points, map_x, map_y, published, display_order
               FROM partner_listings
               WHERE published = true
               ORDER BY display_order, created_at"""
        ).fetchall()
    return jsonify(partners=[partner_json(row) for row in rows])


@app.post("/api/admin/login")
def login():
    validate_same_origin()
    key = request.remote_addr or "unknown"
    now = time.time()
    attempts = [stamp for stamp in login_attempts.get(key, []) if now - stamp < 600]
    if len(attempts) >= 10:
        login_attempts[key] = attempts
        return jsonify(error="試行回数が多すぎます。しばらくしてから再度お試しください。"), 429
    attempts.append(now)
    login_attempts[key] = attempts

    configured_password = admin_secret()
    if not configured_password:
        return jsonify(error="管理用パスワードが設定されていません。"), 503
    payload = request.get_json(silent=True) or {}
    supplied = payload.get("password", "")
    if not isinstance(supplied, str) or not hmac.compare_digest(
        supplied.encode(), configured_password.encode()
    ):
        return jsonify(error="パスワードが違います。"), 401

    expiry = str(int(now) + SESSION_TTL)
    token = f"{expiry}.{session_signature(expiry)}"
    response = make_response(jsonify(ok=True))
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL,
        httponly=True,
        secure=request.is_secure or request.headers.get("X-Forwarded-Proto") == "https",
        samesite="Strict",
        path="/",
    )
    login_attempts.pop(key, None)
    return response


@app.post("/api/admin/logout")
@require_admin
def logout():
    validate_same_origin()
    response = make_response(jsonify(ok=True))
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="Strict")
    return response


@app.get("/api/admin/session")
def admin_session():
    return jsonify(authenticated=is_admin())


@app.get("/api/admin/partners")
@require_admin
def get_admin_partners():
    with db_connection() as conn:
        rows = conn.execute(
            """SELECT id, name, category, area, description, website_url,
                      image_url, nexus_points, map_x, map_y, published, display_order
               FROM partner_listings
               ORDER BY display_order, created_at"""
        ).fetchall()
    return jsonify(partners=[partner_json(row) for row in rows])


@app.post("/api/admin/partners")
@require_admin
def create_partner():
    validate_same_origin()
    payload = request.get_json(silent=True) or {}
    data, error = validate_partner(payload)
    if error:
        return jsonify(error=error), 400
    partner_id = uuid.uuid4()
    with db_connection() as conn:
        if "display_order" not in payload:
            data["display_order"] = conn.execute(
                "SELECT COALESCE(MAX(display_order), 0) + 1 AS next_order FROM partner_listings"
            ).fetchone()["next_order"]
        row = conn.execute(
            """INSERT INTO partner_listings
               (id, name, category, area, description, website_url, image_url,
                nexus_points, map_x, map_y, published, display_order)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id, name, category, area, description, website_url,
                         image_url, nexus_points, map_x, map_y, published, display_order""",
            (
                partner_id, data["name"], data["category"], data["area"],
                data["description"], data["website_url"], data["image_url"],
                data["nexus_points"], data["map_x"], data["map_y"],
                data["published"], data["display_order"],
            ),
        ).fetchone()
    return jsonify(partner=partner_json(row)), 201


@app.put("/api/admin/partners/<uuid:partner_id>")
@require_admin
def update_partner(partner_id):
    validate_same_origin()
    with db_connection() as conn:
        existing = conn.execute(
            """SELECT id, name, category, area, description, website_url,
                      image_url, nexus_points, map_x, map_y, published, display_order
               FROM partner_listings WHERE id = %s""",
            (partner_id,),
        ).fetchone()
        if not existing:
            return jsonify(error="提携先が見つかりません。"), 404
        data, error = validate_partner(request.get_json(silent=True) or {}, existing)
        if error:
            return jsonify(error=error), 400
        row = conn.execute(
            """UPDATE partner_listings SET
                 name = %s, category = %s, area = %s, description = %s,
                 website_url = %s, image_url = %s, nexus_points = %s,
                 map_x = %s, map_y = %s, published = %s, display_order = %s,
                 updated_at = NOW()
               WHERE id = %s
               RETURNING id, name, category, area, description, website_url,
                         image_url, nexus_points, map_x, map_y, published, display_order""",
            (
                data["name"], data["category"], data["area"], data["description"],
                data["website_url"], data["image_url"], data["nexus_points"],
                data["map_x"], data["map_y"], data["published"],
                data["display_order"], partner_id,
            ),
        ).fetchone()
    return jsonify(partner=partner_json(row))


@app.delete("/api/admin/partners/<uuid:partner_id>")
@require_admin
def delete_partner(partner_id):
    validate_same_origin()
    with db_connection() as conn:
        result = conn.execute(
            "DELETE FROM partner_listings WHERE id = %s RETURNING id",
            (partner_id,),
        ).fetchone()
    if not result:
        return jsonify(error="提携先が見つかりません。"), 404
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, threaded=True)
