"""
GS-Prep Backend — Pydantic Schema Models

Defines all request/response schemas for the API.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ========================
# Enums
# ========================

class PipelineStep(str, Enum):
    """Enumeration of all pipeline processing steps."""
    UPLOAD = "upload"
    EXTRACT = "extract"
    BLUR = "blur"
    DUPLICATE = "duplicate"
    RESIZE = "resize"
    REPORT = "report"


class StepStatus(str, Enum):
    """Status of an individual pipeline step."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class DuplicateMethod(str, Enum):
    """Duplicate detection algorithm selection."""
    ORB = "orb"
    SSIM = "ssim"


# ========================
# Video Metadata
# ========================

class VideoMetadata(BaseModel):
    """Metadata extracted from an uploaded video file."""
    filename: str
    duration: float
    fps: float
    total_frames: int
    width: int
    height: int
    codec: str
    file_size: int


# ========================
# Upload
# ========================

class UploadResponse(BaseModel):
    """Response returned after successful video upload."""
    job_id: str
    video_metadata: VideoMetadata


# ========================
# Processing Configuration
# ========================

class ProcessingConfig(BaseModel):
    """Configuration options provided by the user for the pipeline."""
    extraction_fps: int = Field(default=2, ge=1, le=30)
    jpeg_quality: int = Field(default=95, ge=50, le=100)
    blur_threshold: float = Field(default=80.0, ge=10.0, le=500.0)
    duplicate_threshold: float = Field(default=0.85, ge=0.5, le=0.99)
    duplicate_method: DuplicateMethod = Field(default=DuplicateMethod.ORB)
    resize_width: int = Field(default=1920, ge=0, le=7680)


# ========================
# Progress Tracking
# ========================

class StepProgress(BaseModel):
    """Progress for an individual pipeline step."""
    step: PipelineStep
    status: StepStatus = StepStatus.PENDING
    progress: float = Field(default=0.0, ge=0.0, le=100.0)
    message: str = ""
    processed: Optional[int] = None
    total: Optional[int] = None


class PipelineProgress(BaseModel):
    """Overall progress of the active processing pipeline."""
    job_id: str
    steps: List[StepProgress]
    current_step: PipelineStep
    overall_progress: float = Field(default=0.0, ge=0.0, le=100.0)


# ========================
# Final Results
# ========================

class ExtractionResult(BaseModel):
    extraction_fps: int
    total_frames: int
    extracted_frames: int


class BlurResult(BaseModel):
    blur_removed: int
    remaining: int


class DuplicateResult(BaseModel):
    duplicates_removed: int
    remaining: int


class ResizeResult(BaseModel):
    final_width: int
    final_height: int


class DatasetSummary(BaseModel):
    final_images: int


class ProcessingResult(BaseModel):
    """Final summary of the pipeline output."""
    job_id: str
    video_info: VideoMetadata
    extraction: ExtractionResult
    blur: BlurResult
    duplicate: DuplicateResult
    resize: ResizeResult
    dataset_summary: DatasetSummary
    processing_time: float
    report_url: str
    dataset_url: str
    preview_images: List[str]
