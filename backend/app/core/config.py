"""
GS-Prep Backend — Core Configuration Module

Loads environment variables from .env using pydantic-settings.
All application settings are centralized here.
"""

from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "GS-Prep"
    app_version: str = "0.1.0"
    app_env: str = "development"
    debug: bool = True

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # CORS
    cors_origins: List[str] = ["http://localhost:3000"]

    # Storage (relative to backend/ root)
    upload_dir: str = "storage/uploads"
    jobs_dir: str = "storage/jobs"

    # Processing Defaults
    default_extraction_fps: int = 2
    default_jpeg_quality: int = 95
    default_blur_threshold: float = 100.0
    default_duplicate_threshold: float = 0.85
    default_resize_width: int = 1920

    # Limits
    max_upload_size_mb: int = 2048

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
