"""Quick import verification script."""
try:
    from app.core.config import settings
    from app.core.logging import logger
    from app.core.exceptions import GSPrepException
    from app.models.schemas import ProcessingConfig, VideoMetadata, ProcessingResult
    from app.modules.frame_extractor.extractor import FrameExtractor
    from app.modules.blur_detection.detector import BlurDetector
    from app.modules.duplicate_detection.detector import DuplicateDetector
    from app.modules.resize.resizer import ImageResizer
    from app.modules.report.generator import ReportGenerator
    from app.services.pipeline import pipeline_service
    from app.api.v1.health import router as health_router
    from app.api.v1.upload import router as upload_router
    from app.api.v1.pipeline import router as pipeline_router
    print("ALL IMPORTS OK")
except Exception as e:
    print(f"IMPORT ERROR: {e}")
