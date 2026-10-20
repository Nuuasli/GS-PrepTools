import csv
import tempfile
import time
import unittest
import zipfile
from datetime import timedelta
from pathlib import Path

from app.core.config import settings
import cv2
import numpy as np

from app.models.schemas import (
    DuplicateMethod,
    JobStatus,
    ProcessingConfig,
    VideoMetadata,
)
from app.models.manifest import MANIFEST_FIELDS
from app.services.pipeline import PipelineService, utc_now


def video_metadata(filename: str = "sample.mp4") -> VideoMetadata:
    return VideoMetadata(
        filename=filename,
        duration=1.0,
        fps=30.0,
        total_frames=30,
        width=1920,
        height=1080,
        codec="avc1",
        file_size=128,
    )


class PipelineServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_jobs_dir = settings.jobs_dir
        self.old_upload_dir = settings.upload_dir
        root = Path(self.temp_dir.name)
        settings.jobs_dir = str(root / "jobs")
        settings.upload_dir = str(root / "uploads")
        settings.jobs_path.mkdir(parents=True)
        settings.upload_path.mkdir(parents=True)

    def tearDown(self) -> None:
        settings.jobs_dir = self.old_jobs_dir
        settings.upload_dir = self.old_upload_dir
        self.temp_dir.cleanup()

    def test_delete_unknown_job_does_not_delete_other_uploads(self) -> None:
        service = PipelineService()
        known_upload = settings.upload_path / "known.mp4"
        unrelated_upload = settings.upload_path / "unrelated.mp4"
        known_upload.write_bytes(b"known")
        unrelated_upload.write_bytes(b"unrelated")
        job_id = service.create_job(known_upload, video_metadata())

        self.assertFalse(service.delete_job("missing-job"))
        self.assertTrue(known_upload.exists())
        self.assertTrue(unrelated_upload.exists())

        self.assertTrue(service.delete_job(job_id))
        self.assertFalse(known_upload.exists())
        self.assertTrue(unrelated_upload.exists())

    def test_job_metadata_survives_service_restart(self) -> None:
        upload = settings.upload_path / "video.mp4"
        upload.write_bytes(b"video")
        first_service = PipelineService()
        job_id = first_service.create_job(upload, video_metadata())

        restored_service = PipelineService()
        self.assertEqual(restored_service.restore_jobs(), 1)
        restored = restored_service.get_job(job_id)

        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual(restored.status, JobStatus.UPLOADED)
        self.assertEqual(restored.video_metadata.filename, "sample.mp4")

    def test_expired_job_is_removed(self) -> None:
        upload = settings.upload_path / "expired.mp4"
        upload.write_bytes(b"video")
        service = PipelineService()
        job_id = service.create_job(upload, video_metadata("expired.mp4"))
        job = service.get_job(job_id)
        assert job is not None
        job.expires_at = utc_now() - timedelta(seconds=1)
        job.persist()

        self.assertEqual(service.cleanup_expired_jobs(), 1)
        self.assertIsNone(service.get_job(job_id))
        self.assertFalse(upload.exists())

    def test_successful_pipeline_keeps_only_export_artifacts_by_default(self) -> None:
        upload = settings.upload_path / "pipeline.avi"
        writer = cv2.VideoWriter(
            str(upload),
            cv2.VideoWriter_fourcc(*"MJPG"),
            10.0,
            (96, 64),
        )
        self.assertTrue(writer.isOpened())
        random = np.random.default_rng(42)
        for index in range(30):
            frame = random.integers(0, 256, (64, 96, 3), dtype=np.uint8)
            cv2.putText(
                frame,
                str(index),
                (8, 34),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (255, 255, 255),
                2,
            )
            writer.write(frame)
        writer.release()

        service = PipelineService()
        job_id = service.create_job(
            upload,
            VideoMetadata(
                filename="pipeline.avi",
                duration=3.0,
                fps=10.0,
                total_frames=30,
                width=96,
                height=64,
                codec="MJPG",
                file_size=upload.stat().st_size,
            ),
        )
        service.start_pipeline(
            job_id,
            ProcessingConfig(
                extraction_fps=2,
                jpeg_quality=90,
                blur_threshold=10,
                duplicate_threshold=0.99,
                duplicate_method=DuplicateMethod.SSIM,
                resize_width=64,
                keep_intermediates=False,
            ),
        )

        deadline = time.time() + 10
        job = service.get_job(job_id)
        assert job is not None
        while job.status == JobStatus.RUNNING and time.time() < deadline:
            time.sleep(0.05)

        self.assertEqual(job.status, JobStatus.COMPLETED, job.error)
        self.assertIsNotNone(job.result)
        self.assertFalse(upload.exists())
        self.assertFalse(job.output_dir.exists())
        self.assertTrue((job.job_dir / "pipeline_dataset.zip").exists())
        self.assertTrue((job.job_dir / "pipeline_report.pdf").exists())
        self.assertTrue((job.job_dir / "pipeline_manifest.csv").exists())
        self.assertGreater(len(list((job.job_dir / "previews").glob("*.jpg"))), 0)

        with zipfile.ZipFile(job.job_dir / "pipeline_dataset.zip") as archive:
            names = archive.namelist()
            self.assertIn("pipeline/metadata.pdf", names)
            self.assertIn("pipeline/manifest.csv", names)
            self.assertTrue(
                any(name.startswith("pipeline/images/") for name in names)
            )
            self.assertTrue(
                all(
                    name.startswith("pipeline/images/")
                    for name in names
                    if name.lower().endswith(".jpg")
                )
            )

    def test_manifest_records_actual_blur_and_duplicate_decisions(self) -> None:
        upload = settings.upload_path / "manifest_case.avi"
        writer = cv2.VideoWriter(
            str(upload),
            cv2.VideoWriter_fourcc(*"MJPG"),
            4.0,
            (96, 64),
        )
        self.assertTrue(writer.isOpened())

        y_coords, x_coords = np.indices((64, 96))
        checker_gray = (((x_coords // 4) + (y_coords // 4)) % 2 * 255).astype(
            np.uint8
        )
        stripes_gray = ((x_coords // 3) % 2 * 255).astype(np.uint8)
        checker = cv2.cvtColor(checker_gray, cv2.COLOR_GRAY2BGR)
        blurry = np.full((64, 96, 3), 127, dtype=np.uint8)
        stripes = cv2.cvtColor(stripes_gray, cv2.COLOR_GRAY2BGR)

        for frame in (checker, blurry, checker.copy(), stripes):
            writer.write(frame)
        writer.release()

        service = PipelineService()
        job_id = service.create_job(
            upload,
            VideoMetadata(
                filename="manifest_case.avi",
                duration=1.0,
                fps=4.0,
                total_frames=4,
                width=96,
                height=64,
                codec="MJPG",
                file_size=upload.stat().st_size,
            ),
        )
        service.start_pipeline(
            job_id,
            ProcessingConfig(
                extraction_fps=4,
                jpeg_quality=95,
                blur_threshold=50,
                duplicate_threshold=0.95,
                duplicate_method=DuplicateMethod.SSIM,
                resize_width=0,
                keep_intermediates=False,
            ),
        )

        deadline = time.time() + 10
        job = service.get_job(job_id)
        assert job is not None
        while job.status == JobStatus.RUNNING and time.time() < deadline:
            time.sleep(0.05)

        self.assertEqual(job.status, JobStatus.COMPLETED, job.error)
        manifest_path = job.job_dir / "manifest_case_manifest.csv"
        self.assertTrue(manifest_path.exists())
        with manifest_path.open(newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            rows = list(reader)
            self.assertEqual(reader.fieldnames, MANIFEST_FIELDS)

        self.assertEqual(len(rows), 4)
        by_name = {row["filename"]: row for row in rows}
        accepted = by_name["IMG_000001.jpg"]
        rejected_blur = by_name["IMG_000002.jpg"]
        rejected_duplicate = by_name["IMG_000003.jpg"]
        accepted_after_duplicate = by_name["IMG_000004.jpg"]

        self.assertEqual(accepted["status"], "accepted")
        self.assertGreater(float(accepted["blur_score"]), 50)
        self.assertEqual(accepted["duplicate_method"], "SSIM")
        self.assertEqual(accepted["similarity_score"], "")
        self.assertEqual(accepted["compared_with"], "")

        self.assertEqual(rejected_blur["status"], "rejected")
        self.assertEqual(rejected_blur["rejection_reason"], "blur")
        self.assertLess(float(rejected_blur["blur_score"]), 50)
        self.assertEqual(rejected_blur["similarity_score"], "")
        self.assertEqual(rejected_blur["compared_with"], "")

        self.assertEqual(rejected_duplicate["status"], "rejected")
        self.assertEqual(rejected_duplicate["rejection_reason"], "duplicate")
        self.assertGreaterEqual(float(rejected_duplicate["similarity_score"]), 0.95)
        self.assertEqual(rejected_duplicate["compared_with"], "IMG_000001.jpg")

        self.assertEqual(accepted_after_duplicate["status"], "accepted")
        self.assertNotEqual(accepted_after_duplicate["similarity_score"], "")
        self.assertEqual(
            accepted_after_duplicate["compared_with"], "IMG_000001.jpg"
        )

        for expected_index, row in enumerate(rows):
            self.assertEqual(int(row["source_frame_index"]), expected_index)
            self.assertAlmostEqual(
                float(row["source_timestamp"]), expected_index / 4.0, places=6
            )
            self.assertNotEqual(row["blur_score"], "")

        zip_path = job.job_dir / "manifest_case_dataset.zip"
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            self.assertIn("manifest_case/manifest.csv", names)
            self.assertIn("manifest_case/metadata.pdf", names)
            self.assertTrue(
                any(name.startswith("manifest_case/images/") for name in names)
            )

        self.assertFalse(job.output_dir.exists())
        self.assertIsNotNone(job.result)
        assert job.result is not None
        self.assertTrue(job.result.manifest_url)


if __name__ == "__main__":
    unittest.main()
