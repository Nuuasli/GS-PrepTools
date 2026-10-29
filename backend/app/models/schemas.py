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


class JobStatus(str, Enum):
    """Lifecycle status for a processing job."""
    UPLOADED = "uploaded"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class HealthResponse(BaseModel):
    """Runtime status and public upload constraints."""

    status: str
    app_name: str
    version: str
    environment: str
    max_upload_size_mb: int


class DuplicateMethod(str, Enum):
    """Duplicate detection algorithm selection."""
    ORB = "orb"
    SSIM = "ssim"


# ========================
# Video Metadata
# ========================

class ContainerMetadata(BaseModel):
    """Container-level metadata reported by FFprobe."""

    format_name: Optional[str] = None
    format_long_name: Optional[str] = None
    duration: Optional[float] = None
    start_time: Optional[float] = None
    bit_rate: Optional[int] = None
    stream_count: Optional[int] = None


class VideoStreamMetadata(BaseModel):
    """Technical metadata for the primary video stream."""

    stream_index: Optional[int] = None
    codec_name: Optional[str] = None
    codec_long_name: Optional[str] = None
    profile: Optional[str] = None
    level: Optional[int] = None
    pixel_format: Optional[str] = None
    bit_depth: Optional[int] = None
    coded_width: Optional[int] = None
    coded_height: Optional[int] = None
    average_frame_rate: Optional[float] = None
    nominal_frame_rate: Optional[float] = None
    frame_count_source: str = "unknown"
    duration_source: str = "unknown"
    possible_variable_frame_rate: bool = False
    sample_aspect_ratio: Optional[str] = None
    display_aspect_ratio: Optional[str] = None
    rotation: int = 0
    bit_rate: Optional[int] = None
    time_base: Optional[str] = None
    color_range: Optional[str] = None
    color_space: Optional[str] = None
    color_transfer: Optional[str] = None
    color_primaries: Optional[str] = None
    field_order: Optional[str] = None


class AudioStreamMetadata(BaseModel):
    """Summary of the primary audio stream, when present."""

    present: bool = True
    stream_index: Optional[int] = None
    codec_name: Optional[str] = None
    codec_long_name: Optional[str] = None
    profile: Optional[str] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    channel_layout: Optional[str] = None
    bit_rate: Optional[int] = None


class MediaIntegrityMetadata(BaseModel):
    """File identity and provenance of the extracted metadata."""

    sha256: str
    metadata_source: str
    warnings: List[str] = Field(default_factory=list)


class VideoMetadata(BaseModel):
    """Backward-compatible summary plus detailed uploaded-video metadata."""

    filename: str
    duration: float
    fps: float
    total_frames: int
    width: int
    height: int
    codec: str
    file_size: int
    container: Optional[ContainerMetadata] = None
    video_stream: Optional[VideoStreamMetadata] = None
    audio_stream: Optional[AudioStreamMetadata] = None
    integrity: Optional[MediaIntegrityMetadata] = None


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
    jpeg_quality: int = Field(default=100, ge=50, le=100)
    blur_threshold: float = Field(default=10.0, ge=10.0, le=500.0)
    duplicate_threshold: float = Field(default=0.5, ge=0.5, le=0.99)
    duplicate_method: DuplicateMethod = Field(default=DuplicateMethod.ORB)
    resize_width: int = Field(default=0, ge=0, le=7680)
    keep_intermediates: bool = True


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
    status: JobStatus
    error: Optional[str] = None


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
    manifest_url: Optional[str] = None
    preview_images: List[str]
