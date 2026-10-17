import io
import os
import time
import unittest
from unittest.mock import patch

import server


def valid_image_bytes(extension):
    if extension == "jpg":
        return b"\xff\xd8\xffpartner-image\xff\xd9"
    if extension == "png":
        return (
            b"\x89PNG\r\n\x1a\n"
            + b"\x00\x00\x00\rIHDR"
            + b"\x00" * 13
            + b"IEND"
            + b"\x00" * 4
        )
    if extension == "webp":
        payload = b"WEBP" + b"\x00" * 18
        return b"RIFF" + len(payload).to_bytes(4, "little") + payload
    raise AssertionError(f"Unsupported test image extension: {extension}")


class MemoryObjectStorage:
    def __init__(self):
        self.uploaded = []

    def upload_from_bytes(self, object_name, contents):
        self.uploaded.append((object_name, contents))


class PartnerImageUploadTests(unittest.TestCase):
    def setUp(self):
        self.storage = MemoryObjectStorage()
        self.storage_patch = patch.object(
            server, "app_storage_client", return_value=self.storage
        )
        self.storage_patch.start()
        self.addCleanup(self.storage_patch.stop)

        self.env_patch = patch.dict(os.environ, {"SESSION_SECRET": "image-upload-test"})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

        self.client = server.app.test_client()
        expiry = str(int(time.time()) + 3600)
        signature = server.session_signature(expiry)
        self.client.set_cookie(server.SESSION_COOKIE, f"{expiry}.{signature}")

    def upload(self, filename, contents):
        with io.BytesIO(contents) as image_stream:
            response = self.client.post(
                "/api/admin/uploads/partner-image",
                data={"image": (image_stream, filename)},
                content_type="multipart/form-data",
            )
        response.request.close()
        response.request.environ["wsgi.input"].close()
        return response

    def test_non_image_formats_and_misleading_jpeg_extension_are_rejected(self):
        invalid_files = (
            ("animation.gif", b"GIF89a"),
            ("document.pdf", b"%PDF-1.7"),
            ("not-really-a-photo.jpg", b"not a JPEG image"),
        )

        for filename, contents in invalid_files:
            with self.subTest(filename=filename):
                response = self.upload(filename, contents)

                self.assertEqual(response.status_code, 400)
                self.assertIn("JPEG、PNG、WebP", response.get_json()["error"])
                self.assertEqual(self.storage.uploaded, [])

    def test_images_larger_than_five_megabytes_are_rejected(self):
        contents = (
            valid_image_bytes("jpg")
            + b"x" * (server.MAX_PARTNER_IMAGE_BYTES + 1 - len(valid_image_bytes("jpg")))
        )

        response = self.upload("large.jpg", contents)

        self.assertEqual(response.status_code, 413)
        self.assertIn("5MB以下", response.get_json()["error"])
        self.assertEqual(self.storage.uploaded, [])

    def test_image_exactly_five_megabytes_is_saved(self):
        prefix = valid_image_bytes("jpg")[:-2]
        contents = (
            prefix
            + b"x" * (server.MAX_PARTNER_IMAGE_BYTES - len(prefix) - 2)
            + b"\xff\xd9"
        )

        response = self.upload("exact-limit.jpg", contents)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(self.contents_uploaded()), server.MAX_PARTNER_IMAGE_BYTES)

    def test_jpeg_png_and_webp_images_are_saved(self):
        for extension in ("jpg", "png", "webp"):
            with self.subTest(extension=extension):
                contents = valid_image_bytes(extension)

                response = self.upload(f"valid.{extension}", contents)

                self.assertEqual(response.status_code, 201)
                image_url = response.get_json()["image_url"]
                self.assertRegex(
                    image_url,
                    rf"^/uploads/partners/[a-f0-9]{{32}}\.{extension}$",
                )
                self.assertEqual(
                    self.storage.uploaded[-1],
                    (f"partner-images/{image_url.rsplit('/', 1)[1]}", contents),
                )

        self.assertEqual(len(self.storage.uploaded), 3)

    def contents_uploaded(self):
        return self.storage.uploaded[-1][1]


if __name__ == "__main__":
    unittest.main()
