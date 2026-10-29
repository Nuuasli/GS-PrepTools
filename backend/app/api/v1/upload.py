"""
GS-Prep Backend — Upload API Router

Handles video file uploads and metadata extraction.
"""

import hashlib
import logging
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, HTTPException

from app.core.config import settings
from app.core.exceptions import FileTooLargeError, InvalidFileTypeError
from app.models.schemas import UploadResponse
from app.services.pipeline import pipeline_service
from app.services.video_metadata import (
    MetadataExtractionError,
    video_metadata_extractor,
)

logger = logging.getLogger("gs_prep.api.upload")

router = APIRouter(prefix="/upload", tags=["Upload"])

ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".wmv", ".flv"}
UPLOAD_CHUNK_SIZE_BYTES = 1024 * 1024


def validate_upload_size(file_size: int) -> None:
    """Reject byte counts above the configured upload limit."""
    if file_size > settings.max_upload_size_bytes:
        raise FileTooLargeError(
            f"Maximum upload size is {settings.max_upload_size_mb} MB."
        )


@router.post("", response_model=UploadResponse)
async def upload_video(file: UploadFile = File(...)) -> UploadResponse:
    """
    Upload a video file and extract its metadata.

    The video is saved to the uploads directory and metadata
    Detailed metadata is extracted using FFprobe and cross-checked with OpenCV.
    A new processing job is created and the job ID is returned.

    Args:
        file: The uploaded video file.

    Returns:
        UploadResponse: Job ID and video metadata.
    """
    # Validate file type
    raw_filename = (file.filename or "uploaded_video.mp4").replace("\\", "/")
    original_filename = raw_filename.rsplit("/", 1)[-1]
    ext = Path(original_filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise InvalidFileTypeError(
            f"Unsupported file type: {ext}. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Save file
    upload_dir = settings.upload_path
    upload_dir.mkdir(parents=True, exist_ok=True)
    job_id = pipeline_service.new_job_id()
    file_path = upload_dir / f"{job_id}{ext}"

    file_size = 0
    checksum = hashlib.sha256()
    try:
        if file.size is not None:
            validate_upload_size(file.size)
        with open(file_path, "wb") as destination:
            while chunk := await file.read(UPLOAD_CHUNK_SIZE_BYTES):
                file_size += len(chunk)
                validate_upload_size(file_size)
                destination.write(chunk)
                checksum.update(chunk)
    except BaseException:
        # Remove a partial copy on size rejection, disconnect, cancellation,
        # disk-write failure, or any other interrupted upload.
        file_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    logger.info("Video uploaded: %s (%d bytes)", file_path.name, file_size)

    try:
        video_metadata = video_metadata_extractor.extract(
            file_path,
            original_filename=original_filename,
            file_size=file_size,
            sha256=checksum.hexdigest(),
        )
    except MetadataExtractionError as exc:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Create job
    pipeline_service.create_job(file_path, video_metadata, job_id=job_id)

    return UploadResponse(job_id=job_id, video_metadata=video_metadata)
