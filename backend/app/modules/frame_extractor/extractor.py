"""
GS-Prep Backend — Frame Extractor Module

Extracts frames from video at a configurable FPS rate.
Uses OpenCV for video decoding and frame writing.

Output naming convention: IMG_000001.jpg (zero-padded 6 digits)
"""

import logging
from pathlib import Path
from typing import Callable, Optional

import cv2

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
        jpeg_quality: int = 95,
    ):
        self.video_path = video_path
        self.output_dir = output_dir
        self.extraction_fps = extraction_fps
        self.jpeg_quality = jpeg_quality

    def extract(
        self,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> int:
        """
        Extract frames from the video.

        Args:
            on_progress: Optional callback(current, total) for progress tracking.

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

        # Calculate frame interval
        frame_interval = max(1, int(video_fps / self.extraction_fps))

        # Estimate expected extracted frames
        estimated_total = max(1, total_frames // frame_interval)

        logger.info(
            "Extracting frames: video_fps=%.1f, extraction_fps=%d, interval=%d, estimated=%d",
            video_fps,
            self.extraction_fps,
            frame_interval,
            estimated_total,
        )

        extracted_count = 0
        frame_index = 0
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_index % frame_interval == 0:
                extracted_count += 1
                filename = f"{extracted_count:05d}.jpg"
                output_path = self.output_dir / filename
                cv2.imwrite(str(output_path), frame, encode_params)

                if on_progress:
                    on_progress(extracted_count, estimated_total)

            frame_index += 1

        cap.release()
        logger.info("Frame extraction complete: %d frames saved", extracted_count)
        return extracted_count
