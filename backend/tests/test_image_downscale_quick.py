import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from tools.image_downscale.batch import (
    inspect_local_dataset_root,
    quick_preflight_local,
)


def write_image(path: Path, width: int = 2, height: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = np.zeros((height, width, 3), dtype=np.uint8)
    if not cv2.imwrite(str(path), image):
        raise RuntimeError(f"Could not create test image: {path}")


class QuickDryRunTests(unittest.TestCase):
    def test_377_images_inspects_exactly_first_and_last(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_root = root / "input"
            output_root = root / "output"
            for index in range(5, 382):
                write_image(input_root / "Tualen" / f"IMG_{index:06d}.png")

            layout = inspect_local_dataset_root(str(input_root), str(output_root))
            quick = quick_preflight_local(layout)

            dataset = quick.datasets[0]
            self.assertEqual(dataset.total_images, 377)
            self.assertEqual(dataset.sampled_count, 2)
            self.assertEqual(
                [sample.filename for sample in dataset.samples],
                ["IMG_000005.png", "IMG_000381.png"],
            )
            self.assertEqual(quick.total_sampled, 2)
            self.assertFalse(output_root.exists())

    def test_small_datasets_and_large_sample_count_inspect_all(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_root = root / "input"
            output_root = root / "output"
            write_image(input_root / "One" / "only.jpg")
            write_image(input_root / "Two" / "first.jpg")
            write_image(input_root / "Two" / "last.jpg")
            for index in range(3):
                write_image(input_root / "Three" / f"{index}.jpg")
            layout = inspect_local_dataset_root(str(input_root), str(output_root))

            default = quick_preflight_local(layout, samples_per_dataset=2)
            by_name = {dataset.dataset_name: dataset for dataset in default.datasets}
            self.assertEqual(by_name["One"].sampled_count, 1)
            self.assertEqual(by_name["Two"].sampled_count, 2)
            self.assertEqual(by_name["Three"].sampled_count, 2)
            self.assertTrue(all(dataset.sampled_count <= 2 for dataset in default.datasets))

            inspect_all = quick_preflight_local(layout, samples_per_dataset=10)
            self.assertEqual(
                {dataset.dataset_name: dataset.sampled_count for dataset in inspect_all.datasets},
                {"One": 1, "Three": 3, "Two": 2},
            )
            self.assertFalse(output_root.exists())

    def test_sample_resolution_plan_uses_existing_bounding_logic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_root = root / "input"
            output_root = root / "output"
            write_image(input_root / "Ganesha" / "IMG_000001.jpg", 3840, 2160)
            write_image(input_root / "Ganesha" / "IMG_000002.jpg", 1600, 900)
            layout = inspect_local_dataset_root(str(input_root), str(output_root))

            quick = quick_preflight_local(layout, samples_per_dataset=2)
            first, last = quick.datasets[0].samples
            self.assertEqual(
                (first.source_width, first.source_height), (3840, 2160)
            )
            self.assertEqual(
                (first.output_width, first.output_height, first.action),
                (1920, 1080, "resize"),
            )
            self.assertEqual(
                (last.source_width, last.source_height), (1600, 900)
            )
            self.assertEqual(
                (last.output_width, last.output_height, last.action),
                (1600, 900, "unchanged"),
            )
            self.assertEqual(quick.datasets[0].sample_errors, 0)
            self.assertFalse(output_root.exists())


if __name__ == "__main__":
    unittest.main()
