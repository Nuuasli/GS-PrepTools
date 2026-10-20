"""
GS-Prep Backend — Pipeline API Router

Manages pipeline execution, progress polling, results, and file downloads.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.models.schemas import (
    ProcessingConfig,
    PipelineProgress,
    ProcessingResult,
)
from app.services.pipeline import pipeline_service

logger = logging.getLogger("gs_prep.api.pipeline")

router = APIRouter(prefix="/pipeline", tags=["Pipeline"])


@router.post("/{job_id}/start")
async def start_pipeline(job_id: str, config: ProcessingConfig) -> dict:
    """
    Start the processing pipeline for a given job.

    Args:
        job_id: The job identifier returned from upload.
        config: User-configured processing parameters.

    Returns:
        dict: Status confirmation.
    """
    job = pipeline_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    try:
        status = pipeline_service.start_pipeline(job_id, config)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": status, "job_id": job_id}


@router.get("/{job_id}/progress", response_model=PipelineProgress)
async def get_progress(job_id: str) -> PipelineProgress:
    """
    Get current pipeline progress for a job.

    Args:
        job_id: The job identifier.

    Returns:
        PipelineProgress: Current progress across all steps.
    """
    job = pipeline_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    return job.get_progress()


@router.get("/{job_id}/result", response_model=ProcessingResult)
async def get_result(job_id: str) -> ProcessingResult:
    """
    Get the final processing result for a completed job.

    Args:
        job_id: The job identifier.

    Returns:
        ProcessingResult: Complete processing results and download URLs.
    """
    job = pipeline_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    if not job.result:
        raise HTTPException(status_code=202, detail="Processing not yet complete")

    return job.result


@router.get("/{job_id}/download/dataset")
async def download_dataset(job_id: str) -> FileResponse:
    """
    Download the processed dataset as a ZIP archive.

    Args:
        job_id: The job identifier.

    Returns:
        FileResponse: The dataset ZIP file.
    """
    job = pipeline_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    video_name = getattr(job, "video_folder_name", "dataset")
    zip_path = job.job_dir / f"{video_name}_dataset.zip"
    if not zip_path.exists():
        # Fallback for legacy jobs
        zip_path = job.job_dir / "dataset.zip"
        if not zip_path.exists():
            raise HTTPException(status_code=404, detail="Dataset not ready")

    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename=f"{video_name}_dataset.zip",
    )


@router.get("/{job_id}/download/report")
async def download_report(job_id: str) -> FileResponse:
    """
    Download the PDF processing report.

    Args:
        job_id: The job identifier.

    Returns:
        FileResponse: The PDF report file.
    """
    job = pipeline_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    video_name = getattr(job, "video_folder_name", "report")
    report_path = job.job_dir / f"{video_name}_report.pdf"
    if not report_path.exists():
        # Fallback for legacy jobs
        report_path = job.job_dir / "report.pdf"
        if not report_path.exists():
            raise HTTPException(status_code=404, detail="Report not ready")

    return FileResponse(
        path=str(report_path),
        media_type="application/pdf",
        filename=f"{video_name}_report.pdf",
    )


@router.get("/{job_id}/download/manifest")
async def download_manifest(job_id: str) -> FileResponse:
    """Download the per-frame processing manifest as CSV."""
    job = pipeline_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    video_name = getattr(job, "video_folder_name", "dataset")
    manifest_path = job.job_dir / f"{video_name}_manifest.csv"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Manifest not ready")

    return FileResponse(
        path=str(manifest_path),
        media_type="text/csv",
        filename=f"{video_name}_manifest.csv",
    )


@router.get("/{job_id}/preview/{filename}")
async def preview_image(job_id: str, filename: str) -> FileResponse:
    """
    Get a preview image from the processed dataset.

    Args:
        job_id: The job identifier.
        filename: The image filename (e.g., IMG_000001.jpg).

    Returns:
        FileResponse: The image file.
    """
    job = pipeline_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    safe_filename = Path(filename).name
    if safe_filename != filename:
        raise HTTPException(status_code=400, detail="Invalid preview filename")

    image_path = job.job_dir / "previews" / safe_filename
    if not image_path.exists():
        image_path = getattr(job, "output_dir", job.job_dir) / "processed" / safe_filename
        if not image_path.exists():
            raise HTTPException(status_code=404, detail=f"Image not found: {safe_filename}")

    return FileResponse(path=str(image_path), media_type="image/jpeg")


@router.delete("/{job_id}")
async def delete_job(job_id: str) -> dict:
    """
    Delete a processing job and all associated uploaded video files & extracted datasets.

    Args:
        job_id: The job identifier.

    Returns:
        dict: Deletion status.
    """
    try:
        deleted = pipeline_service.delete_job(job_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return {"status": "deleted", "job_id": job_id}
