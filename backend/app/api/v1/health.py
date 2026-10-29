"""
GS-Prep Backend — Health Check Router

Provides system status and health check endpoints.
"""

from fastapi import APIRouter

from app.core.config import settings
from app.models.schemas import HealthResponse

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Application health check endpoint.

    Returns:
        dict: Application name, version, environment, and health status.
    """
    return HealthResponse(
        status="healthy",
        app_name=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
        max_upload_size_mb=settings.max_upload_size_mb,
    )
