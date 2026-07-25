"""
GS-Prep Backend — Health Check Router

Provides system status and health check endpoints.
"""

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("")
async def health_check() -> dict:
    """
    Application health check endpoint.

    Returns:
        dict: Application name, version, environment, and health status.
    """
    return {
        "status": "healthy",
        "app_name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
    }
