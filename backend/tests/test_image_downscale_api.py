import asyncio
import io
import tempfile
import time
import unittest
from pathlib import Path

import cv2
import numpy as np
from fastapi import HTTPException, UploadFile

from app.api.v1.image_downscale import (
    LocalPathPreflightRequest,
    create_local_preflight,
    create_preflight,
    start_batch,
)
from app.core.config import settings
from app.services.image_downscale import image_downscale_service


def image_upload(filename: str, width: int = 64, height: int = 36) -> UploadFile:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    success, buffer = cv2.imencode(Path(filename).suffix or ".jpg", image)
    if not success:
        raise RuntimeError("Could not encode test image")
    return UploadFile(file=io.BytesIO(buffer.tobytes()), filename=filename)


class ImageDownscaleApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_jobs_dir = settings.jobs_dir
        settings.jobs_dir = str(Path(self.temp_dir.name) / "jobs")
        self.job_ids: list[str] = []

    def tearDown(self) -> None:
        for job_id in self.job_ids:
            image_downscale_service.delete(job_id)
        settings.jobs_dir = self.old_jobs_dir
        self.temp_dir.cleanup()

    def test_root_upload_preflight_and_processing_preserve_dataset_scope(self) -> None:
        uploads = [
            image_upload("IMG_000001.jpg", 384, 216),
            image_upload("IMG_000001.jpg", 400, 300),
            UploadFile(file=io.BytesIO(b"notes"), filename="README.txt"),
        ]
        response = asyncio.run(
            create_preflight(
                files=uploads,
                relative_paths=[
                    "Ganesha/IMG_000001.jpg",
                    "Siwa/IMG_000001.jpg",
                    "README.txt",
                ],
                input_mode="root",
                root_name="DATA_PATUNG",
                max_width=192,
                max_height=108,
            )
        )
        job_id = response["job_id"]
        self.job_ids.append(job_id)
        self.assertEqual(response["dataset_count"], 2)
        self.assertEqual(response["total_images"], 2)
        self.assertEqual(response["ignored_files"], ["README.txt"])
        self.assertTrue(response["can_process"])

        asyncio.run(start_batch(job_id))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            job = image_downscale_service.get_job(job_id)
            assert job is not None
            if job.status != "running":
                break
            time.sleep(0.02)
        self.assertEqual(job.status, "completed", job.error)
        assert job.result is not None
        completed = job.as_dict()["result"]
        self.assertEqual(completed["output"], 2)
        for dataset in completed["datasets"]:
            self.assertEqual(
                dataset["resized"] + dataset["unchanged"], dataset["output"]
            )
        self.assertTrue(
            (job.result.output_root / "Ganesha" / "IMG_000001.jpg").is_file()
        )
        self.assertTrue(
            (job.result.output_root / "Siwa" / "IMG_000001.jpg").is_file()
        )
        self.assertTrue(job.result.archive_path.is_file())

    def test_single_folder_mode_and_corrupt_preflight(self) -> None:
        good = asyncio.run(
            create_preflight(
                files=[image_upload("one.png", 64, 64)],
                relative_paths=["one.png"],
                input_mode="single",
                root_name="Tualen",
                max_width=1920,
                max_height=1080,
            )
        )
        self.job_ids.append(good["job_id"])
        self.assertEqual(good["datasets"][0]["dataset_name"], "Tualen")
        self.assertEqual(good["total_unchanged"], 1)
        asyncio.run(start_batch(good["job_id"]))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            single_job = image_downscale_service.get_job(good["job_id"])
            assert single_job is not None
            if single_job.status != "running":
                break
            time.sleep(0.02)
        self.assertEqual(single_job.status, "completed", single_job.error)
        assert single_job.result is not None
        self.assertTrue((single_job.result.output_root / "one.png").is_file())
        self.assertTrue(
            (single_job.result.output_root / "downscale_manifest.csv").is_file()
        )
        self.assertFalse((single_job.result.output_root / "Tualen").exists())

        corrupt = asyncio.run(
            create_preflight(
                files=[UploadFile(file=io.BytesIO(b"broken"), filename="bad.jpg")],
                relative_paths=["Durga/bad.jpg"],
                input_mode="root",
                root_name="DATA_PATUNG",
                max_width=1920,
                max_height=1080,
            )
        )
        self.job_ids.append(corrupt["job_id"])
        self.assertFalse(corrupt["can_process"])
        self.assertEqual(corrupt["status"], "preflight_blocked")
        self.assertEqual(corrupt["corrupt_images"][0]["relative_path"], "Durga/bad.jpg")

    def test_traversal_upload_is_rejected_and_cleaned_up(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                create_preflight(
                    files=[image_upload("evil.jpg")],
                    relative_paths=["../evil.jpg"],
                    input_mode="root",
                    root_name="DATA_PATUNG",
                    max_width=1920,
                    max_height=1080,
                )
            )
        self.assertEqual(raised.exception.status_code, 400)
        storage = image_downscale_service.storage_root
        self.assertTrue(not storage.exists() or not any(storage.iterdir()))

    def test_local_path_api_writes_directly_without_archive(self) -> None:
        input_root = Path(self.temp_dir.name) / "local_input"
        output_root = Path(self.temp_dir.name) / "local_output"
        image = np.zeros((216, 384, 3), dtype=np.uint8)
        (input_root / "Tualen").mkdir(parents=True)
        self.assertTrue(cv2.imwrite(str(input_root / "Tualen" / "image.jpg"), image))

        response = asyncio.run(
            create_local_preflight(
                LocalPathPreflightRequest(
                    input_path=str(input_root),
                    output_path=str(output_root),
                    max_width=192,
                    max_height=108,
                )
            )
        )
        job_id = response["job_id"]
        self.job_ids.append(job_id)
        self.assertEqual(response["input_mode"], "local")
        self.assertEqual(response["input_path"], str(input_root.resolve()))
        self.assertEqual(response["output_path"], str(output_root.resolve()))
        self.assertFalse(output_root.exists())

        asyncio.run(start_batch(job_id))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            job = image_downscale_service.get_job(job_id)
            assert job is not None
            if job.status != "running":
                break
            time.sleep(0.02)
        self.assertEqual(job.status, "completed", job.error)
        assert job.result is not None
        self.assertIsNone(job.result.archive_path)
        self.assertTrue((output_root / "Tualen" / "image.jpg").is_file())
        self.assertTrue(image_downscale_service.delete(job_id))
        self.job_ids.remove(job_id)
        self.assertTrue((output_root / "Tualen" / "image.jpg").is_file())

    def test_non_sampled_corrupt_image_is_caught_by_start_full_preflight(self) -> None:
        input_root = Path(self.temp_dir.name) / "sample_input"
        output_root = Path(self.temp_dir.name) / "sample_output"
        dataset = input_root / "Tualen"
        dataset.mkdir(parents=True)
        image = np.zeros((36, 64, 3), dtype=np.uint8)
        self.assertTrue(cv2.imwrite(str(dataset / "IMG_000001.jpg"), image))
        (dataset / "IMG_000002.jpg").write_bytes(b"corrupt non-sampled image")
        self.assertTrue(cv2.imwrite(str(dataset / "IMG_000003.jpg"), image))

        response = asyncio.run(
            create_local_preflight(
                LocalPathPreflightRequest(
                    input_path=str(input_root),
                    output_path=str(output_root),
                    samples_per_dataset=2,
                )
            )
        )
        job_id = response["job_id"]
        self.job_ids.append(job_id)
        self.assertEqual(response["validation_scope"], "sample")
        self.assertEqual(response["total_images"], 3)
        self.assertEqual(response["total_sampled"], 2)
        self.assertEqual(response["corrupt_images"], [])
        self.assertTrue(response["full_preflight_pending"])
        self.assertTrue(response["can_process"])

        asyncio.run(start_batch(job_id))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            job = image_downscale_service.get_job(job_id)
            assert job is not None
            if job.status != "running":
                break
            time.sleep(0.02)
        self.assertEqual(job.status, "failed")
        self.assertIn("IMG_000002.jpg", job.error or "")
        self.assertFalse(output_root.exists())


if __name__ == "__main__":
    unittest.main()
