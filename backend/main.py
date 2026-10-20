"""
GS-Prep Backend — FastAPI Application Entrypoint

Initializes the FastAPI application, registers middleware,
exception handlers, and API routers.
"""

import asyncio
from contextlib import asynccontextmanager, suppress
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import logger
from app.api.v1.health import router as health_router
from app.api.v1.upload import router as upload_router
from app.api.v1.pipeline import router as pipeline_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan handler.
    Runs startup logic before yield and shutdown logic after.
    """
    # --- Startup ---
    logger.info("Starting %s v%s [%s]", settings.app_name, settings.app_version, settings.app_env)

    # Ensure storage directories exist
    settings.upload_path.mkdir(parents=True, exist_ok=True)
    settings.jobs_path.mkdir(parents=True, exist_ok=True)
    logger.info("Storage directories verified: uploads=%s, jobs=%s", settings.upload_path, settings.jobs_path)

    from app.services.pipeline import pipeline_service

    restored = pipeline_service.restore_jobs()
    if restored > 0:
        logger.info("Restored %d job metadata records", restored)

    purged = pipeline_service.cleanup_expired_jobs()
    if purged > 0:
        logger.info("Housekeeping: Auto-purged %d expired jobs on startup", purged)

    async def housekeeping_loop() -> None:
        while True:
            await asyncio.sleep(settings.cleanup_interval_minutes * 60)
            purged_count = pipeline_service.cleanup_expired_jobs()
            if purged_count > 0:
                logger.info("Housekeeping: purged %d expired jobs", purged_count)

    housekeeping_task = asyncio.create_task(housekeeping_loop())

    try:
        yield
    finally:
        # --- Shutdown ---
        housekeeping_task.cancel()
        with suppress(asyncio.CancelledError):
            await housekeeping_task
        logger.info("Shutting down %s", settings.app_name)


def create_app() -> FastAPI:
    """
    Application factory — constructs and configures the FastAPI instance.

    Returns:
        FastAPI: Fully configured application instance.
    """
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Gaussian Splatting Dataset Preparation Tool — Backend API",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # --- CORS Middleware ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Exception Handlers ---
    register_exception_handlers(app)

    # --- API Routers ---
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(upload_router, prefix="/api/v1")
    app.include_router(pipeline_router, prefix="/api/v1")

    return app


# Application instance (used by uvicorn)
app = create_app()
