"""
GS-Prep Backend — Frame Extractor Module

Extracts frames from video at a configurable FPS rate.
Uses OpenCV for video decoding and frame writing.

Output naming convention: IMG_000001.jpg (zero-padded 6 digits)
"""

import logging
import math
from pathlib import Path
from typing import Callable, Optional

import cv2

from app.models.manifest import ExtractedFrameMetadata

logger = logging.getLogger("gs_prep.modules.frame_extractor")


class FrameExtractor:
    """
    Extracts frames from a video file at the specified FPS.

    Attributes:
        video_path: Path to the source video file.
        output_dir: Directory where extracted frames will be saved.
        extraction_fps: Target frames per second to extract.
        jpeg_quality: JPEG compression quality (1-100).
    """

    def __init__(
        self,
        video_path: Path,
        output_dir: Path,
        extraction_fps: int = 2,
        jpeg_quality: int = 100,
    ):
        self.video_path = video_path
        self.output_dir = output_dir
        self.extraction_fps = extraction_fps
        self.jpeg_quality = jpeg_quality

    def extract(
        self,
        on_progress: Optional[Callable[[int, int], None]] = None,
        on_frame: Optional[Callable[[ExtractedFrameMetadata], None]] = None,
    ) -> int:
        """
        Extract frames from the video.

        Args:
            on_progress: Optional callback(current, total) for progress tracking.
            on_frame: Optional callback containing the source position of each
                successfully written frame.

        Returns:
            int: Number of frames extracted.

        Raises:
            RuntimeError: If the video file cannot be opened.
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)

        cap = cv2.VideoCapture(str(self.video_path))
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {self.video_path}")

        video_fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        if video_fps <= 0:
            cap.release()
            raise RuntimeError("Video reports an invalid FPS value")

        target_fps = min(float(self.extraction_fps), video_fps)
        frame_ratio = video_fps / target_fps
        estimated_total = max(
            1,
            min(total_frames, math.ceil((total_frames / video_fps) * target_fps)),
        )

        logger.info(
            "Extracting frames: video_fps=%.1f, extraction_fps=%.1f, estimated=%d",
            video_fps,
            target_fps,
            estimated_total,
        )

        extracted_count = 0
        frame_index = 0
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            next_sample_index = round(extracted_count * frame_ratio)
            if frame_index >= next_sample_index:
                extracted_count += 1
                filename = f"IMG_{extracted_count:06d}.jpg"
                output_path = self.output_dir / filename
                if not cv2.imwrite(str(output_path), frame, encode_params):
                    cap.release()
                    raise RuntimeError(f"Could not write extracted frame: {output_path}")

                if on_frame:
                    on_frame(
                        ExtractedFrameMetadata(
                            filename=filename,
                            source_frame_index=frame_index,
                            source_timestamp=frame_index / video_fps,
                        )
                    )

                if on_progress:
                    on_progress(extracted_count, estimated_total)

            frame_index += 1

        cap.release()
        logger.info("Frame extraction complete: %d frames saved", extracted_count)
        return extracted_count
