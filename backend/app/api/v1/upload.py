"""
GS-Prep Backend — Upload API Router

Handles video file uploads and metadata extraction.
"""

import logging
from pathlib import Path

import cv2
from fastapi import APIRouter, File, UploadFile, HTTPException

from app.core.config import settings
from app.core.exceptions import FileTooLargeError, InvalidFileTypeError
from app.models.schemas import UploadResponse, VideoMetadata
from app.services.pipeline import pipeline_service

logger = logging.getLogger("gs_prep.api.upload")

router = APIRouter(prefix="/upload", tags=["Upload"])

ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".wmv", ".flv"}


@router.post("", response_model=UploadResponse)
async def upload_video(file: UploadFile = File(...)) -> UploadResponse:
    """
    Upload a video file and extract its metadata.

    The video is saved to the uploads directory and metadata
    (duration, FPS, resolution, codec) is extracted using OpenCV.
    A new processing job is created and the job ID is returned.

    Args:
        file: The uploaded video file.

    Returns:
        UploadResponse: Job ID and video metadata.
    """
    # Validate file type
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise InvalidFileTypeError(
            f"Unsupported file type: {ext}. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Save file
    upload_dir = settings.upload_path
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / (file.filename or "uploaded_video.mp4")

    file_size = 0
    with open(file_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):  # 1MB chunks
            file_size += len(chunk)
            if file_size > settings.max_upload_size_bytes:
                f.close()
                file_path.unlink(missing_ok=True)
                raise FileTooLargeError(
                    f"File exceeds maximum size of {settings.max_upload_size_mb}MB"
                )
            f.write(chunk)

    logger.info("Video uploaded: %s (%d bytes)", file_path.name, file_size)

    # Extract video metadata using OpenCV
    cap = cv2.VideoCapture(str(file_path))
    if not cap.isOpened():
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Cannot read video file")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
    codec = (
        chr(fourcc & 0xFF)
        + chr((fourcc >> 8) & 0xFF)
        + chr((fourcc >> 16) & 0xFF)
        + chr((fourcc >> 24) & 0xFF)
    )
    duration = total_frames / fps if fps > 0 else 0

    cap.release()

    video_metadata = VideoMetadata(
        filename=file_path.name,
        duration=duration,
        fps=fps,
        total_frames=total_frames,
        width=width,
        height=height,
        codec=codec.strip(),
        file_size=file_size,
    )

    # Create job
    job_id = pipeline_service.create_job(file_path, video_metadata)

    return UploadResponse(job_id=job_id, video_metadata=video_metadata)
