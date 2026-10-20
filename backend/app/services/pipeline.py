"""
GS-Prep pipeline orchestration and durable job metadata.

Large processing artifacts remain filesystem-based and temporary. Small job
metadata is persisted as JSON so completed and failed jobs survive a restart.
"""

import json
import logging
import shutil
import time
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock, Thread
from typing import Dict, Optional

from app.core.config import settings
from app.models.schemas import (
    BlurResult,
    DatasetSummary,
    DuplicateResult,
    ExtractionResult,
    JobStatus,
    PipelineProgress,
    PipelineStep,
    ProcessingConfig,
    ProcessingResult,
    ResizeResult,
    StepProgress,
    StepStatus,
    VideoMetadata,
)
from app.models.manifest import FrameManifest
from app.modules.blur_detection.detector import BlurDetector
from app.modules.duplicate_detection.detector import DuplicateDetector
from app.modules.frame_extractor.extractor import FrameExtractor
from app.modules.report.generator import ReportGenerator
from app.modules.resize.resizer import ImageResizer

logger = logging.getLogger("gs_prep.services.pipeline")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JobState:
    """Thread-safe, persistable state for one processing job."""

    def __init__(self, job_id: str, video_path: Path, video_metadata: VideoMetadata):
        self._lock = RLock()
        self.job_id = job_id
        self.video_path = video_path
        self.video_metadata = video_metadata
        self.job_dir = settings.jobs_path / job_id

        video_stem = Path(video_metadata.filename).stem
        clean_name = "".join(
            char if char.isalnum() or char in ("-", "_") else "_"
            for char in video_stem
        ).strip("_")
        self.video_folder_name = clean_name or "curated_dataset"
        self.output_dir = self.job_dir / self.video_folder_name

        self.steps: Dict[PipelineStep, StepProgress] = {
            step: StepProgress(step=step) for step in PipelineStep
        }
        self.steps[PipelineStep.UPLOAD] = StepProgress(
            step=PipelineStep.UPLOAD,
            status=StepStatus.COMPLETED,
            progress=100.0,
            message="Upload complete",
        )
        self.current_step = PipelineStep.EXTRACT
        self.status = JobStatus.UPLOADED
        self.error: Optional[str] = None
        self.result: Optional[ProcessingResult] = None
        self.config: Optional[ProcessingConfig] = None
        self.created_at = utc_now()
        self.updated_at = self.created_at
        self.expires_at = self.created_at + timedelta(
            hours=settings.uploaded_job_ttl_hours
        )

        self.job_dir.mkdir(parents=True, exist_ok=True)
        self.persist()

    @property
    def state_path(self) -> Path:
        return self.job_dir / "job.json"

    def update_step(self, step: PipelineStep, **kwargs: object) -> None:
        with self._lock:
            current = self.steps[step]
            for key, value in kwargs.items():
                if hasattr(current, key):
                    setattr(current, key, value)
            self.updated_at = utc_now()

    def set_status(
        self,
        status: JobStatus,
        *,
        error: Optional[str] = None,
        ttl_hours: Optional[int] = None,
    ) -> None:
        with self._lock:
            self.status = status
            self.error = error
            self.updated_at = utc_now()
            if ttl_hours is not None:
                self.expires_at = self.updated_at + timedelta(hours=ttl_hours)

    def get_progress(self) -> PipelineProgress:
        with self._lock:
            steps = [self.steps[step].model_copy(deep=True) for step in PipelineStep]
            overall = sum(step.progress for step in steps) / len(steps)
            return PipelineProgress(
                job_id=self.job_id,
                steps=steps,
                current_step=self.current_step,
                overall_progress=overall,
                status=self.status,
                error=self.error,
            )

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "job_id": self.job_id,
                "video_path": str(self.video_path),
                "video_metadata": self.video_metadata.model_dump(mode="json"),
                "video_folder_name": self.video_folder_name,
                "steps": [
                    self.steps[step].model_dump(mode="json") for step in PipelineStep
                ],
                "current_step": self.current_step.value,
                "status": self.status.value,
                "error": self.error,
                "result": self.result.model_dump(mode="json") if self.result else None,
                "config": self.config.model_dump(mode="json") if self.config else None,
                "created_at": self.created_at.isoformat(),
                "updated_at": self.updated_at.isoformat(),
                "expires_at": self.expires_at.isoformat(),
            }

    def persist(self) -> None:
        """Atomically persist the small job metadata document."""
        self.job_dir.mkdir(parents=True, exist_ok=True)
        temp_path = self.state_path.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temp_path.replace(self.state_path)

    @classmethod
    def from_file(cls, state_path: Path) -> "JobState":
        data = json.loads(state_path.read_text(encoding="utf-8"))
        job = cls.__new__(cls)
        job._lock = RLock()
        job.job_id = data["job_id"]
        job.video_path = Path(data["video_path"])
        job.video_metadata = VideoMetadata.model_validate(data["video_metadata"])
        job.job_dir = state_path.parent
        job.video_folder_name = data.get("video_folder_name", "curated_dataset")
        job.output_dir = job.job_dir / job.video_folder_name
        job.steps = {
            PipelineStep(item["step"]): StepProgress.model_validate(item)
            for item in data["steps"]
        }
        job.current_step = PipelineStep(data.get("current_step", "extract"))
        job.status = JobStatus(data.get("status", "failed"))
        job.error = data.get("error")
        job.result = (
            ProcessingResult.model_validate(data["result"])
            if data.get("result")
            else None
        )
        job.config = (
            ProcessingConfig.model_validate(data["config"])
            if data.get("config")
            else None
        )
        job.created_at = datetime.fromisoformat(data["created_at"])
        job.updated_at = datetime.fromisoformat(data["updated_at"])
        job.expires_at = datetime.fromisoformat(data["expires_at"])
        return job


class PipelineService:
    """Manage job creation, execution, persistence, and expiration."""

    def __init__(self) -> None:
        self._jobs: Dict[str, JobState] = {}
        self._lock = RLock()

    def new_job_id(self) -> str:
        with self._lock:
            while True:
                job_id = uuid.uuid4().hex[:12]
                if job_id not in self._jobs and not (settings.jobs_path / job_id).exists():
                    return job_id

    def create_job(
        self,
        video_path: Path,
        video_metadata: VideoMetadata,
        *,
        job_id: Optional[str] = None,
    ) -> str:
        job_id = job_id or self.new_job_id()
        job = JobState(job_id, video_path, video_metadata)
        with self._lock:
            self._jobs[job_id] = job
        logger.info("Job created: %s", job_id)
        return job_id

    def restore_jobs(self) -> int:
        """Restore job metadata after a server restart."""
        restored = 0
        settings.jobs_path.mkdir(parents=True, exist_ok=True)
        for state_path in settings.jobs_path.glob("*/job.json"):
            try:
                job = JobState.from_file(state_path)
                if job.status == JobStatus.RUNNING:
                    job.update_step(
                        job.current_step,
                        status=StepStatus.FAILED,
                        message="Interrupted by server restart",
                    )
                    job.set_status(
                        JobStatus.FAILED,
                        error="Processing was interrupted by a server restart.",
                        ttl_hours=settings.failed_job_ttl_hours,
                    )
                    job.persist()
                with self._lock:
                    self._jobs[job.job_id] = job
                restored += 1
            except Exception:
                logger.exception("Could not restore job metadata: %s", state_path)
        return restored

    def get_job(self, job_id: str) -> Optional[JobState]:
        with self._lock:
            return self._jobs.get(job_id)

    def delete_job(self, job_id: str) -> bool:
        """Delete only the requested job; never sweep unrelated uploads."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            if job.status == JobStatus.RUNNING:
                raise RuntimeError("A running job cannot be deleted")
            self._jobs.pop(job_id, None)

        if job.job_dir.exists():
            shutil.rmtree(job.job_dir)
        if job.video_path.exists():
            job.video_path.unlink(missing_ok=True)
        logger.info("Deleted job and artifacts: %s", job_id)
        return True

    def cleanup_expired_jobs(self) -> int:
        """Delete expired non-running jobs and unreferenced stale uploads."""
        now = utc_now()
        with self._lock:
            expired_ids = [
                job_id
                for job_id, job in self._jobs.items()
                if job.status != JobStatus.RUNNING and job.expires_at <= now
            ]

        for job_id in expired_ids:
            try:
                self.delete_job(job_id)
            except Exception:
                logger.exception("Failed to delete expired job: %s", job_id)

        with self._lock:
            referenced_uploads = {
                job.video_path.resolve()
                for job in self._jobs.values()
                if job.video_path.exists()
            }
        cutoff = time.time() - (settings.uploaded_job_ttl_hours * 3600)
        if settings.upload_path.exists():
            for upload in settings.upload_path.iterdir():
                if (
                    upload.is_file()
                    and upload.name != ".gitkeep"
                    and upload.resolve() not in referenced_uploads
                    and upload.stat().st_mtime < cutoff
                ):
                    upload.unlink(missing_ok=True)

        return len(expired_ids)

    def start_pipeline(self, job_id: str, config: ProcessingConfig) -> str:
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        with job._lock:
            if job.status == JobStatus.RUNNING:
                return "already_running"
            if job.status == JobStatus.COMPLETED:
                return "completed"
            if job.status == JobStatus.FAILED:
                raise RuntimeError(
                    "Failed jobs cannot be restarted; upload the video again"
                )
            if not job.video_path.exists():
                raise RuntimeError("Uploaded video is no longer available")

            job.config = config
            job.set_status(JobStatus.RUNNING)
            job.persist()
        Thread(target=self._run_pipeline, args=(job, config), daemon=True).start()
        logger.info("Pipeline started for job %s", job_id)
        return "started"

    @staticmethod
    def _persist_step(job: JobState) -> None:
        try:
            job.persist()
        except Exception:
            logger.exception("Failed to persist job metadata: %s", job.job_id)

    def _run_pipeline(self, job: JobState, config: ProcessingConfig) -> None:
        start_time = time.time()
        frames_dir = job.output_dir / "frames"
        blur_dir = job.output_dir / "blur"
        duplicate_dir = job.output_dir / "duplicate"
        processed_dir = job.output_dir / "processed"
        preview_dir = job.job_dir / "previews"
        report_path = job.job_dir / f"{job.video_folder_name}_report.pdf"
        manifest_path = job.job_dir / f"{job.video_folder_name}_manifest.csv"
        manifest = FrameManifest()

        try:
            job.current_step = PipelineStep.EXTRACT
            job.update_step(
                PipelineStep.EXTRACT,
                status=StepStatus.RUNNING,
                message="Extracting frames...",
            )
            self._persist_step(job)
            extracted_count = FrameExtractor(
                video_path=job.video_path,
                output_dir=frames_dir,
                extraction_fps=config.extraction_fps,
                jpeg_quality=config.jpeg_quality,
            ).extract(
                on_progress=lambda cur, tot: job.update_step(
                    PipelineStep.EXTRACT,
                    progress=min(100.0, (cur / max(tot, 1)) * 100),
                    message=f"Extracting frame {cur}/{tot}",
                    processed=cur,
                    total=tot,
                ),
                on_frame=manifest.record_extraction,
            )
            if extracted_count == 0:
                raise RuntimeError("No frames could be extracted from the video")
            job.update_step(
                PipelineStep.EXTRACT,
                status=StepStatus.COMPLETED,
                progress=100.0,
                message=f"Extracted {extracted_count} frames",
            )
            self._persist_step(job)

            job.current_step = PipelineStep.BLUR
            job.update_step(
                PipelineStep.BLUR,
                status=StepStatus.RUNNING,
                message="Detecting blur...",
            )
            self._persist_step(job)
            blur_removed = BlurDetector(
                frames_dir=frames_dir,
                blur_dir=blur_dir,
                threshold=config.blur_threshold,
            ).detect(
                on_progress=lambda cur, tot: job.update_step(
                    PipelineStep.BLUR,
                    progress=min(100.0, (cur / max(tot, 1)) * 100),
                    message=f"Scanning frame {cur}/{tot}",
                    processed=cur,
                    total=tot,
                ),
                on_decision=manifest.record_blur,
            )
            remaining_after_blur = len(list(frames_dir.glob("*.jpg")))
            if remaining_after_blur == 0:
                raise RuntimeError(
                    "All extracted frames were rejected as blurry; lower the blur threshold"
                )
            job.update_step(
                PipelineStep.BLUR,
                status=StepStatus.COMPLETED,
                progress=100.0,
                message=f"Removed {blur_removed} blurry frames",
            )
            self._persist_step(job)

            job.current_step = PipelineStep.DUPLICATE
            job.update_step(
                PipelineStep.DUPLICATE,
                status=StepStatus.RUNNING,
                message="Detecting duplicates...",
            )
            self._persist_step(job)
            duplicates_removed = DuplicateDetector(
                frames_dir=frames_dir,
                duplicate_dir=duplicate_dir,
                threshold=config.duplicate_threshold,
                method=config.duplicate_method.value,
            ).detect(
                on_progress=lambda cur, tot: job.update_step(
                    PipelineStep.DUPLICATE,
                    progress=min(100.0, (cur / max(tot, 1)) * 100),
                    message=f"Comparing frame {cur}/{tot}",
                    processed=cur,
                    total=tot,
                ),
                on_decision=manifest.record_duplicate,
            )
            remaining_after_dup = len(list(frames_dir.glob("*.jpg")))
            if remaining_after_dup == 0:
                raise RuntimeError("No unique frames remain after duplicate detection")
            job.update_step(
                PipelineStep.DUPLICATE,
                status=StepStatus.COMPLETED,
                progress=100.0,
                message=f"Removed {duplicates_removed} duplicates",
            )
            self._persist_step(job)

            job.current_step = PipelineStep.RESIZE
            job.update_step(
                PipelineStep.RESIZE,
                status=StepStatus.RUNNING,
                message="Preparing final images...",
            )
            self._persist_step(job)
            resized_count, final_w, final_h = ImageResizer(
                frames_dir=frames_dir,
                output_dir=processed_dir,
                target_width=config.resize_width,
                jpeg_quality=config.jpeg_quality,
            ).resize(
                on_progress=lambda cur, tot: job.update_step(
                    PipelineStep.RESIZE,
                    progress=min(100.0, (cur / max(tot, 1)) * 100),
                    message=f"Preparing frame {cur}/{tot}",
                    processed=cur,
                    total=tot,
                )
            )
            if resized_count == 0:
                raise RuntimeError("No final images could be written")
            job.update_step(
                PipelineStep.RESIZE,
                status=StepStatus.COMPLETED,
                progress=100.0,
                message=f"Prepared {resized_count} frames at {final_w}×{final_h}",
            )
            self._persist_step(job)

            job.current_step = PipelineStep.REPORT
            job.update_step(
                PipelineStep.REPORT,
                status=StepStatus.RUNNING,
                message="Generating export...",
            )
            self._persist_step(job)
            processing_time = time.time() - start_time
            final_files = sorted(processed_dir.glob("*.jpg"))
            if len(manifest.records) != extracted_count:
                raise RuntimeError(
                    "Manifest row count does not match extracted frame count"
                )
            manifest.write_csv(manifest_path)

            ReportGenerator(output_path=report_path).generate(
                video_info=job.video_metadata.model_dump(),
                extraction_info={
                    "extraction_fps": config.extraction_fps,
                    "total_frames": job.video_metadata.total_frames,
                    "extracted_frames": extracted_count,
                },
                blur_info={"blur_removed": blur_removed, "remaining": remaining_after_blur},
                duplicate_info={
                    "duplicates_removed": duplicates_removed,
                    "remaining": remaining_after_dup,
                },
                resize_info={"final_width": final_w, "final_height": final_h},
                dataset_info={
                    "final_images": len(final_files),
                    "rejected_blur": blur_removed,
                    "rejected_duplicate": duplicates_removed,
                    "extracted_frames": extracted_count,
                },
                processing_time=processing_time,
            )

            zip_path = job.job_dir / f"{job.video_folder_name}_dataset.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
                for image_path in final_files:
                    archive.write(
                        image_path,
                        arcname=(
                            f"{job.video_folder_name}/images/{image_path.name}"
                        ),
                    )
                archive.write(
                    report_path,
                    arcname=f"{job.video_folder_name}/metadata.pdf",
                )
                archive.write(
                    manifest_path,
                    arcname=f"{job.video_folder_name}/manifest.csv",
                )

            preview_dir.mkdir(parents=True, exist_ok=True)
            preview_images = []
            for image_path in final_files[:8]:
                shutil.copy2(image_path, preview_dir / image_path.name)
                preview_images.append(image_path.name)

            job.result = ProcessingResult(
                job_id=job.job_id,
                video_info=job.video_metadata,
                extraction=ExtractionResult(
                    extraction_fps=config.extraction_fps,
                    total_frames=job.video_metadata.total_frames,
                    extracted_frames=extracted_count,
                ),
                blur=BlurResult(
                    blur_removed=blur_removed,
                    remaining=remaining_after_blur,
                ),
                duplicate=DuplicateResult(
                    duplicates_removed=duplicates_removed,
                    remaining=remaining_after_dup,
                ),
                resize=ResizeResult(final_width=final_w, final_height=final_h),
                dataset_summary=DatasetSummary(final_images=len(final_files)),
                processing_time=processing_time,
                report_url=f"/api/v1/pipeline/{job.job_id}/download/report",
                dataset_url=f"/api/v1/pipeline/{job.job_id}/download/dataset",
                manifest_url=f"/api/v1/pipeline/{job.job_id}/download/manifest",
                preview_images=preview_images,
            )
            job.update_step(
                PipelineStep.REPORT,
                status=StepStatus.COMPLETED,
                progress=100.0,
                message="Export ready",
            )
            if not config.keep_intermediates:
                try:
                    for directory in (frames_dir, blur_dir, duplicate_dir, processed_dir):
                        if directory.exists():
                            shutil.rmtree(directory)
                    if job.output_dir.exists() and not any(job.output_dir.iterdir()):
                        job.output_dir.rmdir()
                    if job.video_path.exists():
                        job.video_path.unlink(missing_ok=True)
                except Exception:
                    logger.exception(
                        "Export succeeded but intermediate cleanup failed for job %s",
                        job.job_id,
                    )

            job.set_status(
                JobStatus.COMPLETED,
                ttl_hours=settings.completed_job_ttl_hours,
            )
            job.persist()

            logger.info(
                "Pipeline complete for job %s: %d final images in %.1fs",
                job.job_id,
                len(final_files),
                processing_time,
            )
        except Exception as exc:
            logger.exception("Pipeline failed for job %s", job.job_id)
            job.update_step(
                job.current_step,
                status=StepStatus.FAILED,
                message=f"Error: {exc}",
            )
            job.set_status(
                JobStatus.FAILED,
                error=str(exc),
                ttl_hours=settings.failed_job_ttl_hours,
            )
            self._persist_step(job)


pipeline_service = PipelineService()
