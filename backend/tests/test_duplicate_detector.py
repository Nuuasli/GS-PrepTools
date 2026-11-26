import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.models.manifest import DuplicateDecision
from app.modules.duplicate_detection.detector import DuplicateDetector


class DuplicateDetectorTests(unittest.TestCase):
    def test_method_switch_calls_only_the_selected_similarity_function(self) -> None:
        for method, selected_name, unselected_name in (
            ("ssim", "compute_ssim_similarity", "compute_orb_similarity"),
            ("orb", "compute_orb_similarity", "compute_ssim_similarity"),
        ):
            with self.subTest(method=method), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                frames_dir = root / "frames"
                duplicate_dir = root / "duplicates"
                frames_dir.mkdir()
                first = frames_dir / "IMG_000001.jpg"
                second = frames_dir / "IMG_000002.jpg"
                first.write_bytes(b"first")
                second.write_bytes(b"second")

                with (
                    patch.object(
                        DuplicateDetector,
                        selected_name,
                        return_value=0.25,
                    ) as selected,
                    patch.object(
                        DuplicateDetector,
                        unselected_name,
                        return_value=0.99,
                    ) as unselected,
                ):
                    decisions: list[DuplicateDecision] = []
                    removed = DuplicateDetector(
                        frames_dir=frames_dir,
                        duplicate_dir=duplicate_dir,
                        threshold=0.98,
                        method=method,
                    ).detect(on_decision=decisions.append)

                selected.assert_called_once_with(first, second)
                unselected.assert_not_called()
                self.assertEqual(removed, 0)
                self.assertEqual(decisions[1].duplicate_method, method)
                self.assertEqual(decisions[1].similarity_score, 0.25)

    def test_orb_exposes_the_score_and_reference_it_used(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            frames_dir = root / "frames"
            duplicate_dir = root / "duplicates"
            frames_dir.mkdir()
            random = np.random.default_rng(7)
            image = random.integers(0, 256, (256, 256, 3), dtype=np.uint8)
            first = frames_dir / "IMG_000001.jpg"
            second = frames_dir / "IMG_000002.jpg"
            self.assertTrue(cv2.imwrite(str(first), image))
            self.assertTrue(cv2.imwrite(str(second), image))

            decisions: list[DuplicateDecision] = []
            removed = DuplicateDetector(
                frames_dir=frames_dir,
                duplicate_dir=duplicate_dir,
                threshold=0.85,
                method="orb",
            ).detect(on_decision=decisions.append)

            self.assertEqual(removed, 1)
            self.assertEqual(len(decisions), 2)
            self.assertIsNone(decisions[0].similarity_score)
            self.assertEqual(decisions[1].compared_with, first.name)
            self.assertEqual(decisions[1].duplicate_method, "orb")
            self.assertIsNotNone(decisions[1].similarity_score)
            assert decisions[1].similarity_score is not None
            self.assertGreaterEqual(decisions[1].similarity_score, 0.85)
            self.assertTrue(decisions[1].is_duplicate)


if __name__ == "__main__":
    unittest.main()
