"""
GS-Prep Backend — Duplicate Detection Module

Detects and removes duplicate/near-duplicate frames using:
  - Primary: ORB Feature Matching
  - Secondary (optional): SSIM (Structural Similarity Index)

Duplicate frames are moved to a separate directory (non-destructive).
"""

import logging
import shutil
from pathlib import Path
from typing import Callable, List, Optional

import cv2
import numpy as np
from skimage.metrics import structural_similarity as ssim

logger = logging.getLogger("gs_prep.modules.duplicate_detection")


class DuplicateDetector:
    """
    Detects and removes duplicate frames from a dataset.

    Attributes:
        frames_dir: Directory containing frames to check.
        duplicate_dir: Directory to move duplicates to.
        threshold: Similarity threshold (0-1). Higher = stricter matching.
        method: Detection method ('orb' or 'ssim').
    """

    def __init__(
        self,
        frames_dir: Path,
        duplicate_dir: Path,
        threshold: float = 0.85,
        method: str = "orb",
    ):
        self.frames_dir = frames_dir
        self.duplicate_dir = duplicate_dir
        self.threshold = threshold
        self.method = method

    @staticmethod
    def compute_orb_similarity(img1_path: Path, img2_path: Path) -> float:
        """
        Compute similarity between two images using ORB feature matching.

        Args:
            img1_path: Path to the first image.
            img2_path: Path to the second image.

        Returns:
            float: Similarity score between 0 and 1.
        """
        img1 = cv2.imread(str(img1_path), cv2.IMREAD_GRAYSCALE)
        img2 = cv2.imread(str(img2_path), cv2.IMREAD_GRAYSCALE)

        if img1 is None or img2 is None:
            return 0.0

        orb = cv2.ORB_create(nfeatures=500)
        kp1, des1 = orb.detectAndCompute(img1, None)
        kp2, des2 = orb.detectAndCompute(img2, None)

        if des1 is None or des2 is None or len(des1) == 0 or len(des2) == 0:
            return 0.0

        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        matches = bf.match(des1, des2)

        if len(matches) == 0:
            return 0.0

        # Similarity = ratio of good matches to total keypoints
        good_matches = [m for m in matches if m.distance < 50]
        max_possible = min(len(kp1), len(kp2))

        if max_possible == 0:
            return 0.0

        return len(good_matches) / max_possible

    @staticmethod
    def compute_ssim_similarity(img1_path: Path, img2_path: Path) -> float:
        """
        Compute SSIM between two images.

        Args:
            img1_path: Path to the first image.
            img2_path: Path to the second image.

        Returns:
            float: SSIM score between 0 and 1.
        """
        img1 = cv2.imread(str(img1_path), cv2.IMREAD_GRAYSCALE)
        img2 = cv2.imread(str(img2_path), cv2.IMREAD_GRAYSCALE)

        if img1 is None or img2 is None:
            return 0.0

        # Resize to same dimensions for comparison
        h = min(img1.shape[0], img2.shape[0], 256)
        w = min(img1.shape[1], img2.shape[1], 256)
        img1 = cv2.resize(img1, (w, h))
        img2 = cv2.resize(img2, (w, h))

        score, _ = ssim(img1, img2, full=True)
        return float(score)

    def detect(
        self,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> int:
        """
        Scan frames sequentially and remove duplicates compared to previous frame.

        Uses a sliding window approach: each frame is compared to its predecessor.
        If similarity exceeds the threshold, the frame is considered a duplicate.

        Args:
            on_progress: Optional callback(current, total) for progress tracking.

        Returns:
            int: Number of duplicate frames removed.
        """
        self.duplicate_dir.mkdir(parents=True, exist_ok=True)

        frames: List[Path] = sorted(self.frames_dir.glob("*.jpg"))
        total = len(frames)
        duplicate_count = 0

        if total <= 1:
            if on_progress:
                on_progress(total, total)
            return 0

        compare_fn = (
            self.compute_orb_similarity
            if self.method == "orb"
            else self.compute_ssim_similarity
        )

        logger.info(
            "Duplicate detection: scanning %d frames, method=%s, threshold=%.2f",
            total,
            self.method,
            self.threshold,
        )

        prev_frame = frames[0]

        for i in range(1, total):
            current_frame = frames[i]
            similarity = compare_fn(prev_frame, current_frame)

            if similarity >= self.threshold:
                shutil.move(
                    str(current_frame),
                    str(self.duplicate_dir / current_frame.name),
                )
                duplicate_count += 1
                logger.debug(
                    "Duplicate detected: %s (similarity=%.3f)",
                    current_frame.name,
                    similarity,
                )
            else:
                # Update reference frame only when current is unique
                prev_frame = current_frame

            if on_progress:
                on_progress(i, total - 1)

        logger.info("Duplicate detection complete: %d duplicates removed", duplicate_count)
        return duplicate_count
