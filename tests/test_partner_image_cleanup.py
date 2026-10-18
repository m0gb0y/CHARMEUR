import os
import time
import unittest
import uuid
from contextlib import contextmanager
from unittest.mock import patch

import server


PARTNER_FIELDS = (
    "id", "name", "category", "area", "description", "staff_name", "staff_role", "website_url",
    "image_url", "nexus_points", "point_courses", "map_x", "map_y",
    "published", "display_order",
)


class MemoryCursor:
    def __init__(self, row=None):
        self.row = row
        self.rows = []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class MemoryPartnerDatabase:
    def __init__(self):
        self.partners = {}
        self.fail_reference_check = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params=()):
        if "SELECT id, label, display_order FROM partner_categories" in query:
            return MemoryCursor(row=None)

        if "SELECT category_id, display_order, is_active" in query:
            return MemoryCursor(row=None)

        if "SELECT EXISTS" in query:
            if self.fail_reference_check:
                self.fail_reference_check = False
                raise RuntimeError("reference lookup failed")
            image_url = params[0]
            return MemoryCursor(
                {"exists": any(row["image_url"] == image_url for row in self.partners.values())}
            )

        if "SELECT id, name, category" in query and "WHERE id = %s" in query:
            row = self.partners.get(uuid.UUID(str(params[0])))
            return MemoryCursor(row.copy() if row else None)

        if "UPDATE partner_listings SET" in query:
            (
                name, category, area, description, staff_name, staff_role, website_url, image_url,
                nexus_points, point_courses, map_x, map_y, published,
                display_order, partner_id,
            ) = params
            row = self.partners[partner_id]
            row.update(
                name=name, category=category, area=area, description=description,
                staff_name=staff_name, staff_role=staff_role,
                website_url=website_url, image_url=image_url,
                nexus_points=nexus_points, point_courses=point_courses,
                map_x=map_x, map_y=map_y,
                published=published, display_order=display_order,
            )
            return MemoryCursor(row.copy())

        if "DELETE FROM partner_listings" in query:
            row = self.partners.pop(uuid.UUID(str(params[0])), None)
            return MemoryCursor(row.copy() if row else None)

        raise AssertionError(f"Unexpected SQL in image-cleanup test: {query}")


class MemoryObjectStorage:
    def __init__(self):
        self.deleted = []

    def delete(self, object_name):
        self.deleted.append(object_name)


class PartnerImageCleanupTests(unittest.TestCase):
    OLD_IMAGE = "/uploads/partners/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg"
    NEW_IMAGE = "/uploads/partners/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.png"

    def setUp(self):
        self.database = MemoryPartnerDatabase()
        self.storage = MemoryObjectStorage()

        @contextmanager
        def connect_to_memory_database():
            yield self.database

        self.db_patch = patch.object(server, "db_connection", connect_to_memory_database)
        self.storage_patch = patch.object(
            server, "app_storage_client", return_value=self.storage
        )
        self.env_patch = patch.dict(os.environ, {"SESSION_SECRET": "image-cleanup-test"})
        self.db_patch.start()
        self.storage_patch.start()
        self.env_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.addCleanup(self.storage_patch.stop)
        self.addCleanup(self.env_patch.stop)

        self.client = server.app.test_client()
        expiry = str(int(time.time()) + 3600)
        signature = server.session_signature(expiry)
        self.client.set_cookie(server.SESSION_COOKIE, f"{expiry}.{signature}")
        self.partner_id = uuid.uuid4()
        self.database.partners[self.partner_id] = self.partner_row(
            self.partner_id, self.OLD_IMAGE
        )

    @staticmethod
    def partner_row(partner_id, image_url):
        return dict(zip(PARTNER_FIELDS, (
            partner_id, "テスト提携先", "hair", "名古屋市", "", "", "", "",
            image_url, 0, "", None, None, True, 1,
        )))

    def update_partner(self, image_url):
        return self.client.put(
            f"/api/admin/partners/{self.partner_id}",
            json={
                "name": "テスト提携先",
                "category": "hair",
                "image_url": image_url,
                "published": True,
            },
        )

    def test_replacing_unshared_managed_image_deletes_old_object(self):
        response = self.update_partner(self.NEW_IMAGE)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.storage.deleted,
            ["partner-images/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg"],
        )

    def test_replacing_shared_image_keeps_object(self):
        other_id = uuid.uuid4()
        self.database.partners[other_id] = self.partner_row(other_id, self.OLD_IMAGE)

        response = self.update_partner(self.NEW_IMAGE)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.storage.deleted, [])

    def test_saving_without_replacing_image_keeps_existing_url(self):
        response = self.update_partner(self.OLD_IMAGE)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["partner"]["image_url"], self.OLD_IMAGE)
        self.assertEqual(
            self.database.partners[self.partner_id]["image_url"], self.OLD_IMAGE
        )
        self.assertEqual(self.storage.deleted, [])

    def test_deleting_partner_deletes_unshared_managed_image(self):
        response = self.client.delete(f"/api/admin/partners/{self.partner_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.storage.deleted,
            ["partner-images/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg"],
        )

    def test_deleting_partner_keeps_image_still_used_by_another_partner(self):
        other_id = uuid.uuid4()
        self.database.partners[other_id] = self.partner_row(other_id, self.OLD_IMAGE)

        response = self.client.delete(f"/api/admin/partners/{self.partner_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.storage.deleted, [])

    def test_reference_check_failure_keeps_image_without_failing_update(self):
        self.database.fail_reference_check = True

        response = self.update_partner(self.NEW_IMAGE)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.storage.deleted, [])


if __name__ == "__main__":
    unittest.main()
