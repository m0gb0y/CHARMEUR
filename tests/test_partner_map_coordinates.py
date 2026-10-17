import os
import re
import time
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import server


ROOT = Path(__file__).resolve().parents[1]
PARTNER_FIELDS = (
    "id", "name", "category", "area", "description", "website_url",
    "image_url", "nexus_points", "map_x", "map_y", "published",
    "display_order",
)


class MemoryCursor:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class MemoryPartnerDatabase:
    """Small SQL-shaped stand-in for exercising the real Flask API routes."""

    def __init__(self):
        self.partners = {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params=()):
        if "INSERT INTO partner_listings" in query:
            row = dict(zip(PARTNER_FIELDS, params))
            self.partners[row["id"]] = row
            return MemoryCursor(row=row.copy())

        if "UPDATE partner_listings SET" in query:
            (
                name, category, area, description, website_url, image_url,
                nexus_points, map_x, map_y, published, display_order, partner_id,
            ) = params
            row = self.partners[partner_id]
            row.update(
                name=name, category=category, area=area, description=description,
                website_url=website_url, image_url=image_url,
                nexus_points=nexus_points, map_x=map_x, map_y=map_y,
                published=published, display_order=display_order,
            )
            return MemoryCursor(row=row.copy())

        if "SELECT id, name, category" in query and "WHERE id = %s" in query:
            partner_id = params[0]
            row = next(
                (row for key, row in self.partners.items() if str(key) == str(partner_id)),
                None,
            )
            return MemoryCursor(row=row.copy() if row else None)

        if "SELECT id, name, category" in query:
            rows = list(self.partners.values())
            if "WHERE published = true" in query:
                rows = [row for row in rows if row["published"]]
            rows.sort(key=lambda row: row["display_order"])
            return MemoryCursor(rows=[row.copy() for row in rows])

        raise AssertionError(f"Unexpected SQL in map-coordinate test: {query}")


class PartnerMapCoordinateFlowTests(unittest.TestCase):
    def setUp(self):
        self.database = MemoryPartnerDatabase()

        @contextmanager
        def connect_to_memory_database():
            yield self.database

        self.db_patch = patch.object(server, "db_connection", connect_to_memory_database)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.env_patch = patch.dict(os.environ, {"SESSION_SECRET": "map-test-session"})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

        self.client = server.app.test_client()
        expiry = str(int(time.time()) + 3600)
        signature = server.session_signature(expiry)
        self.client.set_cookie(server.SESSION_COOKIE, f"{expiry}.{signature}")

    def payload(self, map_x, map_y):
        return {
            "name": "座標テスト提携先",
            "category": "hair",
            "area": "名古屋市",
            "description": "座標保存の回帰テスト",
            "website_url": "",
            "image_url": "",
            "nexus_points": 0,
            "map_x": map_x,
            "map_y": map_y,
            "published": True,
            "display_order": 1,
        }

    def test_admin_selected_coordinates_are_saved_and_used_by_public_map(self):
        admin_html = (ROOT / "admin.html").read_text()
        self.assertIn("map_x: value('map_x') || null", admin_html)
        self.assertIn("map_y: value('map_y') || null", admin_html)

        initial_position = (28.4, 63.7)
        created = self.client.post(
            "/api/admin/partners", json=self.payload(*initial_position)
        )
        self.assertEqual(created.status_code, 201)
        partner = created.get_json()["partner"]
        partner_id = partner["id"]
        self.assertEqual((partner["map_x"], partner["map_y"]), initial_position)
        saved_partner = self.database.partners[uuid.UUID(partner_id)]
        self.assertEqual((saved_partner["map_x"], saved_partner["map_y"]), initial_position)

        public_response = self.client.get("/api/partners")
        self.assertEqual(public_response.status_code, 200)
        public_partner = public_response.get_json()["partners"][0]
        self.assertEqual((public_partner["map_x"], public_partner["map_y"]), initial_position)

        updated_position = (72.3, 19.6)
        updated = self.client.put(
            f"/api/admin/partners/{partner_id}",
            json=self.payload(*updated_position),
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(
            (updated.get_json()["partner"]["map_x"], updated.get_json()["partner"]["map_y"]),
            updated_position,
        )
        saved_partner = self.database.partners[uuid.UUID(partner_id)]
        self.assertEqual((saved_partner["map_x"], saved_partner["map_y"]), updated_position)

        public_after_update = self.client.get("/api/partners").get_json()["partners"][0]
        self.assertEqual(
            (public_after_update["map_x"], public_after_update["map_y"]),
            updated_position,
        )

    def test_public_page_maps_api_coordinates_to_pin_position(self):
        html = (ROOT / "partners.html").read_text()
        self.assertRegex(
            html,
            re.compile(r"x:\s*partner\.map_x\s*\?\?\s*legacy\?\.x\s*\?\?\s*null"),
        )
        self.assertRegex(
            html,
            re.compile(r"y:\s*partner\.map_y\s*\?\?\s*legacy\?\.y\s*\?\?\s*null"),
        )
        self.assertIn(".map(p => ({ partner: p, x: Number(p.x), y: Number(p.y) }))", html)
        self.assertIn("const position = `left:${x}%;top:${y}%;", html)


if __name__ == "__main__":
    unittest.main()
