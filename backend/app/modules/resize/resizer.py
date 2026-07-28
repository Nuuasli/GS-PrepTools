"""
GS-Prep Backend — Image Resize Module

Resizes images to a target width while maintaining aspect ratio.
Uses high-quality bicubic interpolation (cv2.INTER_CUBIC for downscale).
"""

import logging
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import cv2

logger = logging.getLogger("gs_prep.modules.resize")


class ImageResizer:
    """
    Resizes all images in a directory to a target width.

    Maintains original aspect ratio using bicubic interpolation.
    If target_width is 0, copies images at original resolution.

    Attributes:
        frames_dir: Directory containing source frames.
        output_dir: Directory for resized output images.
        target_width: Target width in pixels (0 = keep original).
    """

    def __init__(
        self,
        frames_dir: Path,
        output_dir: Path,
        target_width: int = 1920,
    ):
        self.frames_dir = frames_dir
        self.output_dir = output_dir
        self.target_width = target_width

    def resize(
        self,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> Tuple[int, int, int]:
        """
        Resize all frames to the target width.

        Args:
            on_progress: Optional callback(current, total) for progress tracking.

        Returns:
            Tuple[int, int, int]: (count, final_width, final_height)
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)

        frames: List[Path] = sorted(self.frames_dir.glob("*.jpg"))
        total = len(frames)
        final_width = 0
        final_height = 0

        logger.info("Resize: processing %d frames, target_width=%d", total, self.target_width)

        for i, frame_path in enumerate(frames, 1):
            image = cv2.imread(str(frame_path))
            if image is None:
                continue

            h, w = image.shape[:2]

            if self.target_width > 0 and w > self.target_width:
                # Calculate new height maintaining aspect ratio
                scale = self.target_width / w
                new_w = self.target_width
                new_h = int(h * scale)
                image = cv2.resize(
                    image,
                    (new_w, new_h),
                    interpolation=cv2.INTER_AREA,  # Best for downscaling
                )
                final_width = new_w
                final_height = new_h
            else:
                final_width = w
                final_height = h

            output_path = self.output_dir / frame_path.name
            cv2.imwrite(str(output_path), image, [cv2.IMWRITE_JPEG_QUALITY, 95])

            if on_progress:
                on_progress(i, total)

        logger.info(
            "Resize complete: %d frames, final resolution=%dx%d",
            total,
            final_width,
            final_height,
        )
        return total, final_width, final_height
