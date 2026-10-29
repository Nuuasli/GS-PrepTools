import asyncio
import io
import tempfile
import unittest
from pathlib import Path

from fastapi import UploadFile

from app.api.v1.upload import upload_video, validate_upload_size
from app.core.config import settings
from app.core.exceptions import FileTooLargeError


class UploadLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_upload_dir = settings.upload_dir
        self.old_max_upload_size_mb = settings.max_upload_size_mb
        settings.upload_dir = str(Path(self.temp_dir.name) / "uploads")
        settings.max_upload_size_mb = 3072

    def tearDown(self) -> None:
        settings.upload_dir = self.old_upload_dir
        settings.max_upload_size_mb = self.old_max_upload_size_mb
        self.temp_dir.cleanup()

    def test_limit_accepts_exact_boundary_and_2_21_gb(self) -> None:
        self.assertEqual(settings.max_upload_size_bytes, 3_221_225_472)
        validate_upload_size(3072 * 1024 * 1024)
        validate_upload_size(round(2.21 * 1024 * 1024 * 1024))

    def test_limit_rejects_one_byte_above_boundary(self) -> None:
        with self.assertRaisesRegex(
            FileTooLargeError, "Maximum upload size is 3072 MB"
        ) as raised:
            validate_upload_size((3072 * 1024 * 1024) + 1)
        self.assertEqual(raised.exception.status_code, 413)
        self.assertEqual(
            raised.exception.message, "Maximum upload size is 3072 MB."
        )

    def test_oversized_partial_copy_is_removed(self) -> None:
        settings.max_upload_size_mb = 1
        upload = UploadFile(
            file=io.BytesIO(b"x" * ((1024 * 1024) + 1)),
            filename="oversized.mp4",
        )

        with self.assertRaises(FileTooLargeError):
            asyncio.run(upload_video(upload))

        upload_dir = settings.upload_path
        self.assertTrue(upload_dir.exists())
        self.assertEqual(list(upload_dir.iterdir()), [])

if __name__ == "__main__":
    unittest.main()
