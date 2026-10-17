#!/usr/bin/env python3
"""CHARMEUR static pages plus the protected partner-management API."""
from __future__ import annotations

import hashlib
import hmac
import io
import os
import re
import time
import uuid
import warnings
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from flask import Flask, abort, jsonify, make_response, request, send_from_directory
from PIL import Image, UnidentifiedImageError
from psycopg.rows import dict_row
from replit.object_storage import Client


ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "5000"))
SESSION_COOKIE = "partner_admin_session"
SESSION_TTL = 12 * 60 * 60
MAX_PARTNER_IMAGE_BYTES = 5 * 1024 * 1024
PARTNER_IMAGE_TYPES = {
    "jpg": (
        "image/jpeg",
        lambda data: data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9"),
    ),
    "png": (
        "image/png",
        lambda data: (
            data.startswith(b"\x89PNG\r\n\x1a\n")
            and len(data) >= 33
            and data[12:16] == b"IHDR"
            and data[-8:-4] == b"IEND"
        ),
    ),
    "webp": (
        "image/webp",
        lambda data: (
            len(data) >= 30
            and data[:4] == b"RIFF"
            and int.from_bytes(data[4:8], "little") == len(data) - 8
            and data[8:12] == b"WEBP"
        ),
    ),
}
PARTNER_IMAGE_FORMATS = {
    "jpg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
}
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
app.config["MAX_CONTENT_LENGTH"] = MAX_PARTNER_IMAGE_BYTES + 64 * 1024
login_attempts: dict[str, list[float]] = {}


def db_connection():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(database_url, row_factory=dict_row)


def app_storage_client():
    return Client(bucket_id=os.environ.get("PARTNER_IMAGE_BUCKET_ID"))


def is_decodable_partner_image(contents, extension):
    expected_format = PARTNER_IMAGE_FORMATS[extension]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(contents)) as image:
                if image.format != expected_format:
                    return False
                image.verify()

            with Image.open(io.BytesIO(contents)) as image:
                if image.format != expected_format:
                    return False
                image.load()
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        SyntaxError,
        UnidentifiedImageError,
        ValueError,
    ):
        return False
    return True


def delete_partner_image_if_unreferenced(image_url):
    match = re.fullmatch(
        r"/uploads/partners/([a-f0-9]{32}\.(?:jpg|png|webp))",
        image_url or "",
    )
    if not match:
        return

    try:
        with db_connection() as conn:
            referenced = conn.execute(
                "SELECT EXISTS (SELECT 1 FROM partner_listings WHERE image_url = %s)",
                (image_url,),
            ).fetchone()["exists"]
    except Exception:
        app.logger.exception(
            "Unable to check whether partner image is still referenced; keeping it"
        )
        return

    if referenced:
        return

    try:
        app_storage_client().delete(f"partner-images/{match.group(1)}")
    except Exception:
        app.logger.exception("Unable to delete unused partner image from App Storage")


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
            if field == "image_url" and re.fullmatch(
                r"/uploads/partners/[a-f0-9]{32}\.(?:jpg|png|webp)", value
            ):
                continue
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
    if request.path.startswith("/uploads/partners/") and response.status_code == 200:
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
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


@app.get("/uploads/partners/<filename>")
def partner_image(filename):
    if not re.fullmatch(r"[a-f0-9]{32}\.(?:jpg|png|webp)", filename):
        abort(404)
    try:
        contents = app_storage_client().download_as_bytes(f"partner-images/{filename}")
    except Exception:
        app.logger.exception("Unable to retrieve partner image from App Storage")
        abort(503)
    mime_type = PARTNER_IMAGE_TYPES[filename.rsplit(".", 1)[1]][0]
    response = make_response(contents)
    response.headers["Content-Type"] = mime_type
    response.headers["Content-Disposition"] = "inline"
    return response


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


@app.post("/api/admin/uploads/partner-image")
@require_admin
def upload_partner_image():
    validate_same_origin()
    image = request.files.get("image")
    if image is None or not image.filename:
        return jsonify(error="アップロードする画像を選択してください。"), 400

    contents = image.stream.read(MAX_PARTNER_IMAGE_BYTES + 1)
    if not contents:
        return jsonify(error="画像ファイルが空です。"), 400
    if len(contents) > MAX_PARTNER_IMAGE_BYTES:
        return jsonify(error="画像は5MB以下のファイルを選択してください。"), 413

    extension = next(
        (
            ext for ext, (_, signature_check) in PARTNER_IMAGE_TYPES.items()
            if signature_check(contents)
        ),
        None,
    )
    if extension is None:
        return jsonify(error="JPEG、PNG、WebP形式の画像を選択してください。"), 400
    if not is_decodable_partner_image(contents, extension):
        return jsonify(error="破損しているか、読み込めない画像です。"), 400

    filename = f"{uuid.uuid4().hex}.{extension}"
    try:
        app_storage_client().upload_from_bytes(f"partner-images/{filename}", contents)
    except Exception:
        app.logger.exception("Unable to save partner image to App Storage")
        return jsonify(error="画像の保存先を利用できません。設定を確認して再度お試しください。"), 503
    return jsonify(image_url=f"/uploads/partners/{filename}"), 201


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
        old_image_url = existing["image_url"]
    if old_image_url != data["image_url"]:
        delete_partner_image_if_unreferenced(old_image_url)
    return jsonify(partner=partner_json(row))


@app.delete("/api/admin/partners/<uuid:partner_id>")
@require_admin
def delete_partner(partner_id):
    validate_same_origin()
    with db_connection() as conn:
        result = conn.execute(
            "DELETE FROM partner_listings WHERE id = %s RETURNING id, image_url",
            (partner_id,),
        ).fetchone()
    if not result:
        return jsonify(error="提携先が見つかりません。"), 404
    delete_partner_image_if_unreferenced(result["image_url"])
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, threaded=True)
