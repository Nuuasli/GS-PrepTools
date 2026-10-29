"""
GS-Prep Backend — Core Configuration Module

Loads environment variables from .env using pydantic-settings.
All application settings are centralized here.
"""

from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_prefix="GSPREP_",
        extra="ignore",
    )

    # Application
    app_name: str = Field("GS-Prep", validation_alias="GSPREP_APP_NAME")
    app_version: str = Field("0.1.0", validation_alias="GSPREP_APP_VERSION")
    app_env: str = Field("development", validation_alias="GSPREP_APP_ENV")
    debug: bool = Field(True, validation_alias="GSPREP_DEBUG")

    # Server
    host: str = Field("0.0.0.0", validation_alias="GSPREP_HOST")
    port: int = Field(8000, validation_alias="GSPREP_PORT")

    # CORS
    cors_origins: List[str] = Field(
        default_factory=lambda: ["http://localhost:3000"],
        validation_alias="GSPREP_CORS_ORIGINS",
    )

    # Storage (relative to backend/ root)
    upload_dir: str = Field("storage/uploads", validation_alias="GSPREP_UPLOAD_DIR")
    jobs_dir: str = Field("storage/jobs", validation_alias="GSPREP_JOBS_DIR")
    ffprobe_binary: str = Field("ffprobe", validation_alias="GSPREP_FFPROBE_BINARY")
    ffprobe_timeout_seconds: int = Field(
        120, ge=5, le=1800, validation_alias="GSPREP_FFPROBE_TIMEOUT_SECONDS"
    )

    # Processing Defaults
    default_extraction_fps: int = Field(
        2, validation_alias="GSPREP_DEFAULT_EXTRACTION_FPS"
    )
    default_jpeg_quality: int = Field(
        100, validation_alias="GSPREP_DEFAULT_JPEG_QUALITY"
    )
    default_blur_threshold: float = Field(
        10.0, validation_alias="GSPREP_DEFAULT_BLUR_THRESHOLD"
    )
    default_duplicate_threshold: float = Field(
        0.5, validation_alias="GSPREP_DEFAULT_DUPLICATE_THRESHOLD"
    )
    default_resize_width: int = Field(
        0, validation_alias="GSPREP_DEFAULT_RESIZE_WIDTH"
    )

    # Limits
    max_upload_size_mb: int = Field(
        3072, ge=1, validation_alias="GSPREP_MAX_UPLOAD_SIZE_MB"
    )

    # Job lifecycle
    uploaded_job_ttl_hours: int = Field(
        1, validation_alias="GSPREP_UPLOADED_JOB_TTL_HOURS"
    )
    completed_job_ttl_hours: int = Field(
        24, validation_alias="GSPREP_COMPLETED_JOB_TTL_HOURS"
    )
    failed_job_ttl_hours: int = Field(
        6, validation_alias="GSPREP_FAILED_JOB_TTL_HOURS"
    )
    cleanup_interval_minutes: int = Field(
        15, validation_alias="GSPREP_CLEANUP_INTERVAL_MINUTES"
    )

    @property
    def upload_path(self) -> Path:
        """Absolute path to the upload directory."""
        return Path(__file__).resolve().parent.parent.parent / self.upload_dir

    @property
    def jobs_path(self) -> Path:
        """Absolute path to the jobs directory."""
        return Path(__file__).resolve().parent.parent.parent / self.jobs_dir

    @property
    def max_upload_size_bytes(self) -> int:
        """Maximum upload size in bytes."""
        return self.max_upload_size_mb * 1024 * 1024


# Singleton settings instance
settings = Settings()
