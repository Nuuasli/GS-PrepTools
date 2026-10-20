import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.modules.resize.resizer import ImageResizer


class ImageResizerTests(unittest.TestCase):
    def test_original_resolution_is_copied_without_recompression(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            frames_dir = root / "frames"
            output_dir = root / "output"
            frames_dir.mkdir()
            source = frames_dir / "IMG_000001.jpg"
            image = np.full((24, 32, 3), 127, dtype=np.uint8)
            self.assertTrue(cv2.imwrite(str(source), image))
            source_bytes = source.read_bytes()

            count, width, height = ImageResizer(
                frames_dir=frames_dir,
                output_dir=output_dir,
                target_width=0,
                jpeg_quality=60,
            ).resize()

            self.assertEqual((count, width, height), (1, 32, 24))
            self.assertEqual((output_dir / source.name).read_bytes(), source_bytes)


if __name__ == "__main__":
    unittest.main()
