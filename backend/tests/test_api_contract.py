import unittest

from app.models.schemas import DuplicateMethod, ProcessingConfig
from main import app


class ApiContractTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
