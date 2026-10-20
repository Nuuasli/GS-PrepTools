"""
GS-Prep Backend — Blur Detection Module

Detects blurry frames using Variance of Laplacian.
Frames below the threshold are moved to a separate directory (non-destructive).
"""

import logging
import shutil
from pathlib import Path
from typing import Callable, List, Optional

import cv2

from app.models.manifest import BlurDecision

logger = logging.getLogger("gs_prep.modules.blur_detection")


class BlurDetector:
    """
    Detects and separates blurry images using Variance of Laplacian.

    A lower Laplacian variance indicates a blurrier image.
    Frames with variance below the threshold are moved to blur_dir.

    Attributes:
        frames_dir: Directory containing extracted frames.
        blur_dir: Directory to move blurry frames to.
        threshold: Laplacian variance threshold. Lower = blurrier.
    """

    def __init__(
        self,
        frames_dir: Path,
        blur_dir: Path,
        threshold: float = 10.0,
    ):
        self.frames_dir = frames_dir
        self.blur_dir = blur_dir
        self.threshold = threshold

    @staticmethod
    def compute_blur_score(image_path: Path) -> float:
        """
        Compute the Variance of Laplacian for a single image.

        Args:
            image_path: Path to the image file.

        Returns:
            float: Variance of Laplacian score. Higher = sharper.
        """
        image = cv2.imread(str(image_path))
        if image is None:
            return 0.0
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

    def detect(
        self,
        on_progress: Optional[Callable[[int, int], None]] = None,
        on_decision: Optional[Callable[[BlurDecision], None]] = None,
    ) -> int:
        """
        Scan all frames and move blurry ones to blur_dir.

        Args:
            on_progress: Optional callback(current, total) for progress tracking.
            on_decision: Optional callback receiving the score and decision
                already used by this detector.

        Returns:
            int: Number of blurry frames removed.
        """
        self.blur_dir.mkdir(parents=True, exist_ok=True)

        frames: List[Path] = sorted(self.frames_dir.glob("*.jpg"))
        total = len(frames)
        blur_count = 0

        logger.info("Blur detection: scanning %d frames, threshold=%.1f", total, self.threshold)

        for i, frame_path in enumerate(frames, 1):
            score = self.compute_blur_score(frame_path)

            is_blurry = score < self.threshold
            if is_blurry:
                shutil.move(str(frame_path), str(self.blur_dir / frame_path.name))
                blur_count += 1
                logger.debug("Blur detected: %s (score=%.1f)", frame_path.name, score)

            if on_decision:
                on_decision(
                    BlurDecision(
                        filename=frame_path.name,
                        blur_score=score,
                        is_blurry=is_blurry,
                    )
                )

            if on_progress:
                on_progress(i, total)

        logger.info("Blur detection complete: %d blurry frames removed", blur_count)
        return blur_count
