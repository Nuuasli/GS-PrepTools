import asyncio
import unittest

from app.api.v1.health import health_check
from app.core.config import settings
from app.models.schemas import DuplicateMethod, ProcessingConfig
from main import app


class ApiContractTests(unittest.TestCase):
    def test_health_exposes_configured_upload_limit(self) -> None:
        health = asyncio.run(health_check())

        self.assertEqual(health.max_upload_size_mb, settings.max_upload_size_mb)

    def test_processing_defaults_match_the_ui_defaults(self) -> None:
        config = ProcessingConfig()

        self.assertEqual(config.extraction_fps, 2)
        self.assertEqual(config.blur_threshold, 10.0)
        self.assertEqual(config.duplicate_threshold, 0.5)
        self.assertEqual(config.jpeg_quality, 100)
        self.assertEqual(config.duplicate_method, DuplicateMethod.ORB)
        self.assertEqual(config.resize_width, 0)
        self.assertTrue(config.keep_intermediates)

    def test_manifest_download_and_result_schema_are_exposed(self) -> None:
        openapi = app.openapi()
        self.assertIn(
            "/api/v1/pipeline/{job_id}/download/manifest",
            openapi["paths"],
        )
        result_schema = openapi["components"]["schemas"]["ProcessingResult"]
        self.assertIn("manifest_url", result_schema["properties"])
        metadata_schema = openapi["components"]["schemas"]["VideoMetadata"]
        self.assertIn("container", metadata_schema["properties"])
        self.assertIn("video_stream", metadata_schema["properties"])
        self.assertIn("audio_stream", metadata_schema["properties"])
        self.assertIn("integrity", metadata_schema["properties"])
        health_schema = openapi["components"]["schemas"]["HealthResponse"]
        self.assertIn("max_upload_size_mb", health_schema["properties"])

    def test_standalone_image_downscale_web_api_is_exposed(self) -> None:
        paths = app.openapi()["paths"]
        self.assertIn("/api/v1/image-downscale/preflight", paths)
        self.assertIn("/api/v1/image-downscale/local/preflight", paths)
        self.assertIn("/api/v1/image-downscale/local/start", paths)
        self.assertIn("/api/v1/image-downscale/{job_id}/start", paths)
        self.assertIn("/api/v1/image-downscale/{job_id}/status", paths)
        self.assertIn("/api/v1/image-downscale/{job_id}/download/zip", paths)
        self.assertIn("/api/v1/image-downscale/{job_id}/download/summary", paths)


if __name__ == "__main__":
    unittest.main()
