import csv
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from tools.image_downscale.batch import (
    BatchDownscaleError,
    inspect_local_dataset_root,
    preflight_batch,
    run_batch_downscale,
)


def write_image(path: Path, width: int, height: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :, 1] = 127
    if not cv2.imwrite(str(path), image):
        raise RuntimeError(f"Could not create test image: {path}")


class ImageDownscaleLocalPathTests(unittest.TestCase):
    def test_direct_local_processing_preserves_structure_and_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_root = root / "DATA_PATUNG"
            output_root = root / "DATA_PATUNG_1080p"
            dimensions = {
                "Ganesha/large.jpg": (3840, 2160),
                "Ganesha/exact.jpg": (1920, 1080),
                "Siwa/smaller.jpg": (1600, 900),
                "Siwa/hd.png": (1280, 720),
            }
            for relative, (width, height) in dimensions.items():
                write_image(input_root / relative, width, height)
            (input_root / "README.txt").write_text("research", encoding="utf-8")
            source_bytes = {
                relative: (input_root / relative).read_bytes()
                for relative in dimensions
            }

            layout = inspect_local_dataset_root(str(input_root), str(output_root))
            self.assertTrue(Path(str(layout.input_root)).is_absolute())
            self.assertEqual(layout.output_root, output_root.resolve())
            self.assertEqual(
                layout.dataset_names,
                {"Ganesha": "Ganesha", "Siwa": "Siwa"},
            )
            self.assertEqual(layout.ignored_files, ("README.txt",))
            dry_run = preflight_batch(
                layout.input_root,
                layout.dataset_names,
                root_name=layout.input_root.name,
                dataset_sources=layout.dataset_sources,
                ignored_files=layout.ignored_files,
            )
            self.assertEqual(dry_run.total_images, 4)
            self.assertEqual(dry_run.total_resize, 1)
            self.assertEqual(dry_run.total_unchanged, 3)
            self.assertFalse(output_root.exists())

            result = run_batch_downscale(
                layout.input_root,
                layout.output_root.parent,
                layout.dataset_names,
                root_name=layout.input_root.name,
                dataset_sources=layout.dataset_sources,
                direct_output_root=layout.output_root,
                create_archive=False,
            )

            self.assertEqual(result.output_root, output_root.resolve())
            self.assertIsNone(result.archive_path)
            self.assertEqual(result.resized_images, 1)
            self.assertEqual(result.unchanged_images, 3)
            self.assertEqual(result.output_images, 4)
            self.assertEqual(
                cv2.imread(str(output_root / "Ganesha" / "large.jpg")).shape[1::-1],
                (1920, 1080),
            )
            for relative in ("Ganesha/exact.jpg", "Siwa/smaller.jpg", "Siwa/hd.png"):
                self.assertEqual(
                    (output_root / relative).read_bytes(), source_bytes[relative]
                )
            for dataset in ("Ganesha", "Siwa"):
                self.assertTrue(
                    (output_root / dataset / "downscale_manifest.csv").is_file()
                )
            with (output_root / "batch_downscale_summary.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            for row in rows:
                self.assertEqual(
                    int(row["resized_images"]) + int(row["unchanged_images"]),
                    int(row["output_images"]),
                )
            self.assertEqual(
                source_bytes,
                {
                    relative: (input_root / relative).read_bytes()
                    for relative in dimensions
                },
            )

    def test_unsafe_or_unavailable_local_paths_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_root = root / "input"
            input_root.mkdir()
            write_image(input_root / "Dataset" / "one.jpg", 32, 18)

            with self.assertRaisesRegex(BatchDownscaleError, "different"):
                inspect_local_dataset_root(str(input_root), str(input_root))
            with self.assertRaisesRegex(BatchDownscaleError, "inside"):
                inspect_local_dataset_root(
                    str(input_root), str(input_root / "downscaled")
                )
            with self.assertRaisesRegex(BatchDownscaleError, "does not exist"):
                inspect_local_dataset_root(
                    str(root / "missing"), str(root / "output")
                )
            existing_output = root / "existing"
            existing_output.mkdir()
            with self.assertRaisesRegex(BatchDownscaleError, "already exists"):
                inspect_local_dataset_root(str(input_root), str(existing_output))

    def test_corrupt_image_blocks_local_processing_without_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_root = root / "input"
            output_root = root / "output"
            write_image(input_root / "Ganesha" / "good.jpg", 32, 18)
            broken = input_root / "Siwa" / "broken.jpg"
            broken.parent.mkdir(parents=True)
            broken.write_bytes(b"not an image")
            layout = inspect_local_dataset_root(str(input_root), str(output_root))
            preflight = preflight_batch(
                layout.input_root,
                layout.dataset_names,
                root_name=layout.input_root.name,
                dataset_sources=layout.dataset_sources,
            )
            self.assertFalse(preflight.can_process)
            with self.assertRaisesRegex(BatchDownscaleError, "broken.jpg"):
                run_batch_downscale(
                    layout.input_root,
                    layout.output_root.parent,
                    layout.dataset_names,
                    root_name=layout.input_root.name,
                    dataset_sources=layout.dataset_sources,
                    direct_output_root=layout.output_root,
                    create_archive=False,
                )
            self.assertFalse(output_root.exists())


if __name__ == "__main__":
    unittest.main()
