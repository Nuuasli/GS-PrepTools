"""
GS-Prep Backend — Pipeline Orchestrator Service

Manages the full processing pipeline lifecycle:
  Upload → Extract → Blur Detection → Duplicate Removal → Resize → Report

Tracks progress for each step and stores results per job.
"""

import logging
import shutil
import time
import uuid
import zipfile
from pathlib import Path
from threading import Thread
from typing import Dict, List, Optional

import cv2

from app.core.config import settings
from app.models.schemas import (
    PipelineStep,
    StepStatus,
    StepProgress,
    PipelineProgress,
    ProcessingConfig,
    ProcessingResult,
    VideoMetadata,
    ExtractionResult,
    BlurResult,
    DuplicateResult,
    ResizeResult,
    DatasetSummary,
)
from app.modules.frame_extractor.extractor import FrameExtractor
from app.modules.blur_detection.detector import BlurDetector
from app.modules.duplicate_detection.detector import DuplicateDetector
from app.modules.resize.resizer import ImageResizer
from app.modules.report.generator import ReportGenerator

logger = logging.getLogger("gs_prep.services.pipeline")


class JobState:
    """Tracks the state of a single processing job."""

    def __init__(self, job_id: str, video_path: Path, video_metadata: VideoMetadata):
        self.job_id = job_id
        self.video_path = video_path
        self.video_metadata = video_metadata
        self.job_dir = settings.jobs_path / job_id

        # Sanitize video filename to create a clean folder name matching the video
        video_stem = Path(video_metadata.filename).stem
        sanitized_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in video_stem).strip("_")
        self.video_folder_name = sanitized_name if sanitized_name else "extracted_dataset"

        # Output directory matching the video name inside the job folder
        self.output_dir = self.job_dir / self.video_folder_name

        # Step progress tracking
        self.steps: Dict[PipelineStep, StepProgress] = {
            step: StepProgress(step=step) for step in PipelineStep
        }
        # Mark upload as already completed
        self.steps[PipelineStep.UPLOAD] = StepProgress(
            step=PipelineStep.UPLOAD,
            status=StepStatus.COMPLETED,
            progress=100.0,
            message="Upload complete",
        )

        self.current_step = PipelineStep.EXTRACT
        self.result: Optional[ProcessingResult] = None

    def update_step(self, step: PipelineStep, **kwargs) -> None:
        """Update progress for a specific step."""
        current = self.steps[step]
        for key, value in kwargs.items():
            if hasattr(current, key):
                setattr(current, key, value)

    def get_progress(self) -> PipelineProgress:
        """Get current pipeline progress."""
        steps_list = [self.steps[step] for step in PipelineStep]
        overall = sum(s.progress for s in steps_list) / len(steps_list)
        return PipelineProgress(
            job_id=self.job_id,
            steps=steps_list,
            current_step=self.current_step,
            overall_progress=overall,
        )


class PipelineService:
    """
    Singleton service that manages all processing jobs.

    Handles job creation, background processing, progress tracking, and results.
    """

    def __init__(self):
        self._jobs: Dict[str, JobState] = {}

    def create_job(self, video_path: Path, video_metadata: VideoMetadata) -> str:
        """Create a new processing job."""
        job_id = str(uuid.uuid4())[:8]
        job = JobState(job_id, video_path, video_metadata)
        self._jobs[job_id] = job
        logger.info("Job created: %s", job_id)
        return job_id

    def get_job(self, job_id: str) -> Optional[JobState]:
        """Get a job by its ID."""
        return self._jobs.get(job_id)

    def delete_job(self, job_id: str) -> bool:
        """Delete a processing job and all associated uploaded video files & extracted datasets."""
        job = self._jobs.pop(job_id, None)

        job_dir = settings.jobs_path / job_id
        if job_dir.exists():
            try:
                shutil.rmtree(job_dir)
                logger.info("Deleted job directory: %s", job_dir)
            except Exception as e:
                logger.error("Failed to delete job directory %s: %s", job_dir, e)

        if job and job.video_path and job.video_path.exists():
            try:
                job.video_path.unlink(missing_ok=True)
                logger.info("Deleted uploaded video: %s", job.video_path)
            except Exception as e:
                logger.error("Failed to delete video %s: %s", job.video_path, e)
        else:
            self._cleanup_all_uploads()

        return True

    def _cleanup_all_uploads(self) -> None:
        """Remove all uploaded video files from the uploads directory."""
        if settings.upload_path.exists():
            for item in settings.upload_path.iterdir():
                if item.is_file() and item.name != ".gitkeep":
                    try:
                        item.unlink(missing_ok=True)
                        logger.info("Cleaned up orphaned upload: %s", item.name)
                    except Exception as e:
                        logger.error("Failed to clean upload %s: %s", item.name, e)

    def cleanup_old_jobs(self, max_age_hours: int = 2) -> int:
        """Automatically purges jobs and storage files older than max_age_hours."""
        now = time.time()
        max_age_sec = max_age_hours * 3600
        purged_count = 0

        if settings.jobs_path.exists():
            for item in settings.jobs_path.iterdir():
                if item.is_dir() and item.name != ".gitkeep":
                    mtime = item.stat().st_mtime
                    if (now - mtime) > max_age_sec:
                        try:
                            shutil.rmtree(item)
                            self._jobs.pop(item.name, None)
                            purged_count += 1
                            logger.info("Auto-purged expired job directory: %s", item.name)
                        except Exception as e:
                            logger.error("Failed auto-purge job %s: %s", item.name, e)

        if settings.upload_path.exists():
            for item in settings.upload_path.iterdir():
                if item.is_file() and item.name != ".gitkeep":
                    mtime = item.stat().st_mtime
                    if (now - mtime) > max_age_sec:
                        try:
                            item.unlink(missing_ok=True)
                            logger.info("Auto-purged expired upload video: %s", item.name)
                        except Exception as e:
                            logger.error("Failed auto-purge upload %s: %s", item.name, e)

        return purged_count

    def start_pipeline(self, job_id: str, config: ProcessingConfig) -> None:
        """Start the processing pipeline in a background thread."""
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")

        thread = Thread(target=self._run_pipeline, args=(job, config), daemon=True)
        thread.start()
        logger.info("Pipeline started for job %s", job_id)

    def _run_pipeline(self, job: JobState, config: ProcessingConfig) -> None:
        """Execute the full processing pipeline sequentially."""
        start_time = time.time()

        frames_dir = job.output_dir / "frames"
        blur_dir = job.output_dir / "blur"
        duplicate_dir = job.output_dir / "duplicate"
        processed_dir = job.output_dir / "processed"
        report_path = job.job_dir / f"{job.video_folder_name}_report.pdf"

        try:
            # ---- Step 1: Extract Frames ----
            job.current_step = PipelineStep.EXTRACT
            job.update_step(PipelineStep.EXTRACT, status=StepStatus.RUNNING, message="Extracting frames...")

            extractor = FrameExtractor(
                video_path=job.video_path,
                output_dir=frames_dir,
                extraction_fps=config.extraction_fps,
                jpeg_quality=config.jpeg_quality,
            )
            extracted_count = extractor.extract(
                on_progress=lambda cur, tot: job.update_step(
                    PipelineStep.EXTRACT,
                    progress=min(100.0, (cur / max(tot, 1)) * 100),
                    message=f"Extracting frame {cur}/{tot}",
                    processed=cur,
                    total=tot,
                )
            )
            job.update_step(
                PipelineStep.EXTRACT,
                status=StepStatus.COMPLETED,
                progress=100.0,
                message=f"Extracted {extracted_count} frames",
            )

            # ---- Step 2: Blur Detection ----
            job.current_step = PipelineStep.BLUR
            job.update_step(PipelineStep.BLUR, status=StepStatus.RUNNING, message="Detecting blur...")

            blur_detector = BlurDetector(
                frames_dir=frames_dir,
                blur_dir=blur_dir,
                threshold=config.blur_threshold,
            )
            blur_removed = blur_detector.detect(
                on_progress=lambda cur, tot: job.update_step(
                    PipelineStep.BLUR,
                    progress=min(100.0, (cur / max(tot, 1)) * 100),
                    message=f"Scanning frame {cur}/{tot}",
                    processed=cur,
                    total=tot,
                )
            )
            remaining_after_blur = len(list(frames_dir.glob("IMG_*.jpg")))
            job.update_step(
                PipelineStep.BLUR,
                status=StepStatus.COMPLETED,
                progress=100.0,
                message=f"Removed {blur_removed} blurry frames",
            )

            # ---- Step 3: Duplicate Removal ----
            job.current_step = PipelineStep.DUPLICATE
            job.update_step(PipelineStep.DUPLICATE, status=StepStatus.RUNNING, message="Detecting duplicates...")

            dup_detector = DuplicateDetector(
                frames_dir=frames_dir,
                duplicate_dir=duplicate_dir,
                threshold=config.duplicate_threshold,
                method=config.duplicate_method.value,
            )
            duplicates_removed = dup_detector.detect(
                on_progress=lambda cur, tot: job.update_step(
                    PipelineStep.DUPLICATE,
                    progress=min(100.0, (cur / max(tot, 1)) * 100),
                    message=f"Comparing frame {cur}/{tot}",
                    processed=cur,
                    total=tot,
                )
            )
            remaining_after_dup = len(list(frames_dir.glob("IMG_*.jpg")))
            job.update_step(
                PipelineStep.DUPLICATE,
                status=StepStatus.COMPLETED,
                progress=100.0,
                message=f"Removed {duplicates_removed} duplicates",
            )

            # ---- Step 4: Resize ----
            job.current_step = PipelineStep.RESIZE
            job.update_step(PipelineStep.RESIZE, status=StepStatus.RUNNING, message="Resizing images...")

            resizer = ImageResizer(
                frames_dir=frames_dir,
                output_dir=processed_dir,
                target_width=config.resize_width,
            )
            resized_count, final_w, final_h = resizer.resize(
                on_progress=lambda cur, tot: job.update_step(
                    PipelineStep.RESIZE,
                    progress=min(100.0, (cur / max(tot, 1)) * 100),
                    message=f"Resizing frame {cur}/{tot}",
                    processed=cur,
                    total=tot,
                )
            )
            job.update_step(
                PipelineStep.RESIZE,
                status=StepStatus.COMPLETED,
                progress=100.0,
                message=f"Resized {resized_count} frames to {final_w}×{final_h}",
            )

            # ---- Step 5: Generate Report ----
            job.current_step = PipelineStep.REPORT
            job.update_step(PipelineStep.REPORT, status=StepStatus.RUNNING, message="Generating report...")

            processing_time = time.time() - start_time
            final_images = len(list(processed_dir.glob("IMG_*.jpg")))

            report_gen = ReportGenerator(output_path=report_path)
            report_gen.generate(
                video_info=job.video_metadata.model_dump(),
                extraction_info={
                    "extraction_fps": config.extraction_fps,
                    "total_frames": job.video_metadata.total_frames,
                    "extracted_frames": extracted_count,
                },
                blur_info={
                    "blur_removed": blur_removed,
                    "remaining": remaining_after_blur,
                },
                duplicate_info={
                    "duplicates_removed": duplicates_removed,
                    "remaining": remaining_after_dup,
                },
                resize_info={
                    "final_width": final_w,
                    "final_height": final_h,
                },
                dataset_info={
                    "final_images": final_images,
                },
                processing_time=processing_time,
            )

            # Create zip archive of processed dataset
            zip_path = job.job_dir / f"{job.video_folder_name}_dataset.zip"
            with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
                for img_file in sorted(processed_dir.glob("IMG_*.jpg")):
                    zf.write(str(img_file), arcname=f"{job.video_folder_name}/{img_file.name}")

            job.update_step(
                PipelineStep.REPORT,
                status=StepStatus.COMPLETED,
                progress=100.0,
                message="Report generated",
            )

            # Get preview images (first 8)
            preview_images = [
                f.name for f in sorted(processed_dir.glob("IMG_*.jpg"))[:8]
            ]

            # Store final result
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
                resize=ResizeResult(
                    final_width=final_w,
                    final_height=final_h,
                ),
                dataset_summary=DatasetSummary(
                    final_images=final_images,
                ),
                processing_time=processing_time,
                report_url=f"/api/v1/pipeline/{job.job_id}/download/report",
                dataset_url=f"/api/v1/pipeline/{job.job_id}/download/dataset",
                preview_images=preview_images,
            )

            logger.info(
                "Pipeline complete for job %s: %d final images in %.1fs",
                job.job_id,
                final_images,
                processing_time,
            )

        except Exception as e:
            logger.error("Pipeline failed for job %s: %s", job.job_id, str(e))
            job.update_step(
                job.current_step,
                status=StepStatus.FAILED,
                message=f"Error: {str(e)}",
            )


# Singleton instance
pipeline_service = PipelineService()
