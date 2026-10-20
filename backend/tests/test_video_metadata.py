import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.models.schemas import VideoMetadata
from app.services.video_metadata import (
    MetadataExtractionError,
    OpenCVProbe,
    VideoMetadataExtractor,
)


FFPROBE_PAYLOAD = {
    "streams": [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": "h264",
            "codec_long_name": "H.264 / AVC",
            "profile": "High",
            "level": 40,
            "width": 1920,
            "height": 1080,
            "coded_width": 1920,
            "coded_height": 1088,
            "pix_fmt": "yuv420p",
            "bits_per_raw_sample": "8",
            "avg_frame_rate": "30000/1001",
            "r_frame_rate": "60/1",
            "nb_read_frames": "300",
            "nb_frames": "299",
            "duration": "10.01",
            "bit_rate": "8000000",
            "time_base": "1/90000",
            "sample_aspect_ratio": "1:1",
            "display_aspect_ratio": "16:9",
            "color_range": "tv",
            "color_space": "bt709",
            "color_transfer": "bt709",
            "color_primaries": "bt709",
            "field_order": "progressive",
            "side_data_list": [{"rotation": -90}],
        },
        {
            "index": 1,
            "codec_type": "audio",
            "codec_name": "aac",
            "codec_long_name": "AAC",
            "profile": "LC",
            "sample_rate": "48000",
            "channels": 2,
            "channel_layout": "stereo",
            "bit_rate": "192000",
        },
    ],
    "format": {
        "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        "format_long_name": "QuickTime / MOV",
        "duration": "10.010000",
        "start_time": "0.000000",
        "bit_rate": "8400000",
        "nb_streams": 2,
    },
}


class VideoMetadataExtractorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.extractor = VideoMetadataExtractor("ffprobe", 30)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.video_path = Path(self.temp_dir.name) / "video.mp4"
        self.video_path.write_bytes(b"fixture")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _extract(self) -> VideoMetadata:
        return self.extractor.extract(
            self.video_path,
            original_filename="original.mp4",
            file_size=7,
            sha256="abc123",
        )

    def test_ffprobe_metadata_is_primary_and_complete(self) -> None:
        with (
            patch.object(self.extractor, "_run_ffprobe", return_value=FFPROBE_PAYLOAD),
            patch.object(self.extractor, "_run_ffprobe_frame_count") as frame_count,
            patch.object(
                self.extractor,
                "_opencv_probe",
                return_value=OpenCVProbe(29.97002997, 300, 1920, 1080, "avc1"),
            ),
        ):
            metadata = self._extract()

        self.assertAlmostEqual(metadata.fps, 30000 / 1001)
        self.assertEqual(metadata.total_frames, 299)
        self.assertEqual(metadata.codec, "h264")
        self.assertEqual(metadata.container.bit_rate, 8_400_000)
        self.assertEqual(
            metadata.video_stream.frame_count_source, "ffprobe_stream_header"
        )
        self.assertEqual(metadata.video_stream.rotation, 270)
        self.assertTrue(metadata.video_stream.possible_variable_frame_rate)
        self.assertEqual(metadata.video_stream.color_space, "bt709")
        self.assertEqual(metadata.audio_stream.sample_rate, 48_000)
        self.assertEqual(metadata.integrity.sha256, "abc123")
        self.assertEqual(metadata.integrity.metadata_source, "ffprobe")
        frame_count.assert_not_called()

    def test_missing_exact_frame_count_is_marked_as_estimate(self) -> None:
        payload = {
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "vp9",
                    "width": 1280,
                    "height": 720,
                    "avg_frame_rate": "25/1",
                }
            ],
            "format": {"duration": "4.0", "format_name": "matroska"},
        }
        with (
            patch.object(self.extractor, "_run_ffprobe", return_value=payload),
            patch.object(
                self.extractor,
                "_run_ffprobe_frame_count",
                side_effect=MetadataExtractionError(
                    "FFprobe frame count timed out after 30 seconds"
                ),
            ),
            patch.object(
                self.extractor,
                "_opencv_probe",
                side_effect=MetadataExtractionError("not available"),
            ),
        ):
            metadata = self._extract()

        self.assertEqual(metadata.total_frames, 100)
        self.assertEqual(
            metadata.video_stream.frame_count_source,
            "duration_times_average_fps_estimate",
        )
        self.assertTrue(
            any("estimated" in warning for warning in metadata.integrity.warnings)
        )
        self.assertTrue(
            any("timed out" in warning for warning in metadata.integrity.warnings)
        )
        self.assertEqual(metadata.integrity.metadata_source, "ffprobe")

    def test_primary_probe_does_not_decode_all_frames(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(FFPROBE_PAYLOAD), stderr=""
        )
        with patch(
            "app.services.video_metadata.subprocess.run", return_value=completed
        ) as run:
            self.extractor._run_ffprobe(self.video_path)

        command = run.call_args.args[0]
        self.assertNotIn("-count_frames", command)
        self.assertIn("-show_format", command)
        self.assertIn("-show_streams", command)

    def test_secondary_frame_count_is_used_when_header_count_is_missing(self) -> None:
        payload = {
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 640,
                    "height": 360,
                    "avg_frame_rate": "30/1",
                }
            ],
            "format": {"duration": "2.0", "format_name": "matroska"},
        }
        with (
            patch.object(self.extractor, "_run_ffprobe", return_value=payload),
            patch.object(
                self.extractor, "_run_ffprobe_frame_count", return_value=61
            ),
            patch.object(
                self.extractor,
                "_opencv_probe",
                return_value=OpenCVProbe(30.0, 61, 640, 360, "avc1"),
            ),
        ):
            metadata = self._extract()

        self.assertEqual(metadata.total_frames, 61)
        self.assertEqual(
            metadata.video_stream.frame_count_source, "ffprobe_count_frames"
        )
        self.assertEqual(metadata.integrity.metadata_source, "ffprobe")

    def test_opencv_is_used_when_ffprobe_is_unavailable(self) -> None:
        with (
            patch.object(
                self.extractor,
                "_run_ffprobe",
                side_effect=MetadataExtractionError("FFprobe unavailable"),
            ),
            patch.object(
                self.extractor,
                "_opencv_probe",
                return_value=OpenCVProbe(24.0, 240, 640, 480, "MJPG"),
            ),
        ):
            metadata = self._extract()

        self.assertEqual(metadata.duration, 10.0)
        self.assertEqual(metadata.integrity.metadata_source, "opencv_fallback")
        self.assertEqual(metadata.video_stream.frame_count_source, "opencv_header")
        self.assertIn("FFprobe unavailable", metadata.integrity.warnings)

    def test_file_without_video_stream_is_rejected(self) -> None:
        payload = {
            "streams": [{"index": 0, "codec_type": "audio", "codec_name": "aac"}],
            "format": {"duration": "3"},
        }
        with patch.object(self.extractor, "_run_ffprobe", return_value=payload):
            with self.assertRaisesRegex(MetadataExtractionError, "no video stream"):
                self._extract()

    def test_legacy_video_metadata_payload_remains_valid(self) -> None:
        metadata = VideoMetadata.model_validate(
            {
                "filename": "legacy.mp4",
                "duration": 1.0,
                "fps": 30.0,
                "total_frames": 30,
                "width": 1920,
                "height": 1080,
                "codec": "h264",
                "file_size": 100,
            }
        )
        self.assertIsNone(metadata.container)
        self.assertIsNone(metadata.video_stream)
        self.assertIsNone(metadata.integrity)

    @unittest.skipUnless(shutil.which("ffprobe"), "FFprobe is not installed")
    def test_real_ffprobe_process_counts_generated_frames(self) -> None:
        path = Path(self.temp_dir.name) / "generated.avi"
        writer = cv2.VideoWriter(
            str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (32, 24)
        )
        self.assertTrue(writer.isOpened())
        for index in range(12):
            writer.write(np.full((24, 32, 3), index * 10, dtype=np.uint8))
        writer.release()
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()

        metadata = self.extractor.extract(
            path,
            original_filename="generated.avi",
            file_size=path.stat().st_size,
            sha256=checksum,
        )

        self.assertEqual(metadata.total_frames, 12)
        self.assertEqual((metadata.width, metadata.height), (32, 24))
        self.assertAlmostEqual(metadata.fps, 10.0, places=3)
        self.assertEqual(metadata.integrity.sha256, checksum)
        self.assertEqual(metadata.integrity.metadata_source, "ffprobe")


if __name__ == "__main__":
    unittest.main()
