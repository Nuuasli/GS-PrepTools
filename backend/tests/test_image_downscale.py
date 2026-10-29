import csv
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import cv2
import numpy as np

from tools.image_downscale.cli import main
from tools.image_downscale.runner import (
    DownscaleError,
    calculate_output_dimensions,
    run_downscale,
)


def write_image(path: Path, width: int, height: int) -> None:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :, 1] = 127
    if not cv2.imwrite(str(path), image):
        raise RuntimeError(f"Could not create test image: {path}")


class ImageDownscaleTests(unittest.TestCase):
    def test_bounding_dimensions_preserve_aspect_ratio_and_never_upscale(self) -> None:
        self.assertEqual(
            calculate_output_dimensions(3840, 2160, 1920, 1080),
            (1920, 1080),
        )
        self.assertEqual(
            calculate_output_dimensions(2560, 1440, 1920, 1080),
            (1920, 1080),
        )
        self.assertEqual(
            calculate_output_dimensions(4000, 3000, 1920, 1080),
            (1440, 1080),
        )
        self.assertEqual(
            calculate_output_dimensions(1920, 1080, 1920, 1080),
            (1920, 1080),
        )
        self.assertEqual(
            calculate_output_dimensions(1600, 900, 1920, 1080),
            (1600, 900),
        )
        self.assertEqual(
            calculate_output_dimensions(1440, 1080, 1920, 1080),
            (1440, 1080),
        )
        self.assertEqual(
            calculate_output_dimensions(1280, 720, 1920, 1080),
            (1280, 720),
        )

    def test_images_inside_bounding_box_are_copied_byte_for_byte(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir = root / "input"
            output_dir = root / "output"
            input_dir.mkdir()
            dimensions = {
                "exact.jpg": (1920, 1080),
                "smaller.jpg": (1600, 900),
                "height_bound.png": (1440, 1080),
                "hd.png": (1280, 720),
                "large.jpg": (3840, 2160),
            }
            for filename, (width, height) in dimensions.items():
                write_image(input_dir / filename, width, height)
            source_bytes = {
                filename: (input_dir / filename).read_bytes()
                for filename in dimensions
            }

            summary = run_downscale(input_dir, output_dir)

            self.assertEqual(summary.image_count, 5)
            self.assertEqual(summary.resized_count, 1)
            self.assertEqual(summary.unchanged_count, 4)
            for filename in ("exact.jpg", "smaller.jpg", "height_bound.png", "hd.png"):
                self.assertEqual(
                    (output_dir / filename).read_bytes(),
                    source_bytes[filename],
                    filename,
                )
            resized = cv2.imread(str(output_dir / "large.jpg"))
            self.assertIsNotNone(resized)
            self.assertEqual(resized.shape[1::-1], (1920, 1080))

            with (output_dir / "downscale_manifest.csv").open(
                encoding="utf-8", newline=""
            ) as csv_file:
                rows = {row["filename"]: row for row in csv.DictReader(csv_file)}
            for filename, (width, height) in dimensions.items():
                row = rows[filename]
                if filename == "large.jpg":
                    self.assertEqual(row["resized"], "true")
                    self.assertEqual(
                        (row["output_width"], row["output_height"]),
                        ("1920", "1080"),
                    )
                else:
                    self.assertEqual(row["resized"], "false")
                    self.assertEqual(
                        (row["source_width"], row["source_height"]),
                        (str(width), str(height)),
                    )
                    self.assertEqual(
                        (row["output_width"], row["output_height"]),
                        (str(width), str(height)),
                    )
                    self.assertEqual(row["source_size_bytes"], row["output_size_bytes"])

            plans = {plan.filename: plan for plan in summary.plans}
            self.assertEqual(plans["large.jpg"].status, "resized")
            for filename in (
                "exact.jpg",
                "smaller.jpg",
                "height_bound.png",
                "hd.png",
            ):
                self.assertEqual(plans[filename].status, "unchanged")

    def test_downscale_writes_images_and_deterministic_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir = root / "extracted"
            output_dir = root / "extracted_1080p"
            input_dir.mkdir()
            write_image(input_dir / "IMG_000002.jpg", 4000, 3000)
            write_image(input_dir / "IMG_000001.jpg", 3840, 2160)
            write_image(input_dir / "IMG_000003.png", 1280, 720)
            unchanged_bytes = (input_dir / "IMG_000003.png").read_bytes()
            source_hashes = {
                path.name: path.read_bytes()
                for path in input_dir.iterdir()
                if path.is_file()
            }

            summary = run_downscale(input_dir, output_dir)

            self.assertEqual(summary.image_count, 3)
            self.assertEqual(summary.resized_count, 2)
            self.assertEqual(summary.unchanged_count, 1)
            first = cv2.imread(str(output_dir / "IMG_000001.jpg"))
            second = cv2.imread(str(output_dir / "IMG_000002.jpg"))
            self.assertEqual(first.shape[1::-1], (1920, 1080))
            self.assertEqual(second.shape[1::-1], (1440, 1080))
            self.assertEqual(
                (output_dir / "IMG_000003.png").read_bytes(), unchanged_bytes
            )
            for name, original_bytes in source_hashes.items():
                self.assertEqual((input_dir / name).read_bytes(), original_bytes)

            manifest = output_dir / "downscale_manifest.csv"
            with manifest.open(encoding="utf-8", newline="") as csv_file:
                reader = csv.DictReader(csv_file)
                rows = list(reader)
            self.assertEqual(
                reader.fieldnames,
                [
                    "filename",
                    "source_width",
                    "source_height",
                    "output_width",
                    "output_height",
                    "resized",
                    "source_size_bytes",
                    "output_size_bytes",
                ],
            )
            self.assertEqual(
                [row["filename"] for row in rows],
                ["IMG_000001.jpg", "IMG_000002.jpg", "IMG_000003.png"],
            )
            self.assertEqual(rows[0]["output_width"], "1920")
            self.assertEqual(rows[0]["output_height"], "1080")
            self.assertEqual(rows[1]["output_width"], "1440")
            self.assertEqual(rows[1]["output_height"], "1080")
            self.assertEqual(rows[2]["resized"], "false")
            self.assertGreater(int(rows[0]["output_size_bytes"]), 0)

    def test_dry_run_prints_plan_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir = root / "extracted"
            output_dir = root / "planned_output"
            input_dir.mkdir()
            write_image(input_dir / "IMG_000001.jpeg", 2560, 1440)
            write_image(input_dir / "IMG_000002.png", 1280, 720)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--input",
                        str(input_dir),
                        "--output",
                        str(output_dir),
                        "--dry-run",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertFalse(output_dir.exists())
            output = stdout.getvalue()
            self.assertIn("DRY RUN - no files written", output)
            self.assertIn("Images: 2", output)
            self.assertIn("Will resize: 1", output)
            self.assertIn("Unchanged: 1", output)
            self.assertIn("2560x1440 -> 1920x1080", output)

    def test_collision_is_rejected_without_force_and_source_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir = root / "extracted"
            output_dir = root / "output"
            input_dir.mkdir()
            output_dir.mkdir()
            source = input_dir / "IMG_000001.jpg"
            destination = output_dir / source.name
            write_image(source, 3840, 2160)
            destination.write_bytes(b"existing")
            source_bytes = source.read_bytes()

            with self.assertRaisesRegex(DownscaleError, "--force"):
                run_downscale(input_dir, output_dir)

            self.assertEqual(destination.read_bytes(), b"existing")
            self.assertEqual(source.read_bytes(), source_bytes)

            summary = run_downscale(input_dir, output_dir, force=True)
            self.assertEqual(summary.resized_count, 1)
            written = cv2.imread(str(destination))
            self.assertIsNotNone(written)
            self.assertEqual(written.shape[1::-1], (1920, 1080))
            self.assertTrue((output_dir / "downscale_manifest.csv").is_file())
            self.assertNotEqual(destination.read_bytes(), b"existing")

    def test_corrupt_image_and_same_output_directory_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / "extracted"
            input_dir.mkdir()
            (input_dir / "broken.jpg").write_bytes(b"not-an-image")
            output_dir = Path(temp_dir) / "output"

            with self.assertRaisesRegex(DownscaleError, "broken.jpg"):
                run_downscale(input_dir, output_dir)
            self.assertFalse(output_dir.exists())

            with self.assertRaisesRegex(DownscaleError, "different"):
                run_downscale(input_dir, input_dir, dry_run=True)


if __name__ == "__main__":
    unittest.main()
