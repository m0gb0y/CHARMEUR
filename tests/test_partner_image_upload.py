import io
import os
import time
import unittest
from unittest.mock import patch

import server
from PIL import Image


def valid_image_bytes(extension):
    image_format = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP"}.get(extension)
    if image_format is None:
        raise AssertionError(f"Unsupported test image extension: {extension}")

    image_buffer = io.BytesIO()
    Image.new("RGB", (2, 2), color=(30, 90, 150)).save(
        image_buffer, format=image_format
    )
    return image_buffer.getvalue()


def jpeg_bytes_of_exact_size(size):
    contents = valid_image_bytes("jpg")
    padding_size = size - len(contents)
    if padding_size < 0:
        raise AssertionError("Target size is smaller than the JPEG fixture")

    segment_count = (padding_size + 65536) // 65537
    segments = []
    for index in range(segment_count):
        segment_size = padding_size // segment_count
        if index < padding_size % segment_count:
            segment_size += 1
        if segment_size < 4 or segment_size > 65537:
            raise AssertionError("Unable to pad JPEG to the requested size")
        payload_size = segment_size - 4
        segments.append(
            b"\xff\xfe"
            + (payload_size + 2).to_bytes(2, "big")
            + b"x" * payload_size
        )

    return contents[:-2] + b"".join(segments) + contents[-2:]


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

    def test_corrupted_jpeg_png_and_webp_images_are_rejected_before_storage(self):
        corrupted_png = bytearray(valid_image_bytes("png"))
        corrupted_png[41] ^= 0xFF
        invalid_images = (
            ("broken.jpg", b"\xff\xd8\xffnot a decodable JPEG\xff\xd9"),
            ("broken.png", bytes(corrupted_png)),
            (
                "broken.webp",
                b"RIFF" + (22).to_bytes(4, "little") + b"WEBP" + b"\x00" * 18,
            ),
        )

        for filename, contents in invalid_images:
            with self.subTest(filename=filename):
                response = self.upload(filename, contents)

                self.assertEqual(response.status_code, 400)
                self.assertIn("破損", response.get_json()["error"])
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

    def test_upload_far_over_request_limit_returns_json_size_error(self):
        contents = b"x" * (server.app.config["MAX_CONTENT_LENGTH"] + 1024 * 1024)

        response = self.upload("very-large.jpg", contents)

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.mimetype, "application/json")
        self.assertIn("5MB以下", response.get_json()["error"])
        self.assertEqual(self.storage.uploaded, [])

    def test_image_exactly_five_megabytes_is_saved(self):
        contents = jpeg_bytes_of_exact_size(server.MAX_PARTNER_IMAGE_BYTES)

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
