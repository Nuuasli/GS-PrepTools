import csv
import tempfile
import unittest
import zipfile
from pathlib import Path

import cv2
import numpy as np

from tools.image_downscale.batch import (
    BATCH_SUMMARY_FILENAME,
    BatchDownscaleError,
    is_supported_image,
    parse_browser_relative_path,
    preflight_batch,
    run_batch_downscale,
    sanitize_component,
)


def write_image(path: Path, width: int, height: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :, 1] = 127
    if not cv2.imwrite(str(path), image):
        raise RuntimeError(f"Could not create test image: {path}")


class ImageDownscaleBatchTests(unittest.TestCase):
    def test_multiple_datasets_detected_with_different_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            write_image(source / "Ganesha" / "IMG_000001.jpg", 3840, 2160)
            write_image(source / "Ganesha" / "IMG_000002.png", 1280, 720)
            write_image(source / "Siwa" / "IMG_000001.jpg", 2560, 1440)

            preflight = preflight_batch(
                source,
                {"Ganesha": "Ganesha", "Siwa": "Siwa"},
                root_name="DATA_PATUNG",
            )

            self.assertEqual(preflight.dataset_count, 2)
            self.assertEqual(preflight.total_images, 3)
            self.assertEqual(preflight.total_resize, 2)
            self.assertEqual(preflight.total_unchanged, 1)
            self.assertTrue(preflight.can_process)
            self.assertEqual(
                [(item.dataset_id, item.images) for item in preflight.datasets],
                [("Ganesha", 2), ("Siwa", 1)],
            )

    def test_batch_preserves_folders_manifests_summary_zip_and_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            first = source / "Ganesha" / "IMG_000001.jpg"
            second = source / "Siwa" / "IMG_000001.jpg"
            unchanged = source / "Siwa" / "small.png"
            write_image(first, 3840, 2160)
            write_image(second, 4000, 3000)
            write_image(unchanged, 1280, 720)
            source_bytes = {
                path.relative_to(source).as_posix(): path.read_bytes()
                for path in source.rglob("*")
                if path.is_file()
            }
            progress: list[tuple[int, int, str]] = []

            result = run_batch_downscale(
                source,
                root / "published",
                {"Ganesha": "Ganesha", "Siwa": "Siwa"},
                root_name="DATA_PATUNG",
                progress=lambda index, total, name: progress.append(
                    (index, total, name)
                ),
            )

            self.assertEqual(progress, [(1, 2, "Ganesha"), (2, 2, "Siwa")])
            self.assertTrue((result.output_root / "Ganesha" / first.name).is_file())
            self.assertTrue((result.output_root / "Siwa" / second.name).is_file())
            self.assertTrue(
                (result.output_root / "Ganesha" / "downscale_manifest.csv").is_file()
            )
            self.assertTrue(
                (result.output_root / "Siwa" / "downscale_manifest.csv").is_file()
            )
            with result.summary_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([row["dataset_id"] for row in rows], ["Ganesha", "Siwa"])
            self.assertEqual(rows[0]["status"], "completed")
            self.assertEqual(rows[1]["unchanged_images"], "1")
            self.assertEqual(rows[0]["output_images"], "1")
            self.assertEqual(rows[1]["output_images"], "2")
            for row in rows:
                self.assertEqual(
                    int(row["resized_images"]) + int(row["unchanged_images"]),
                    int(row["output_images"]),
                )

            with zipfile.ZipFile(result.archive_path) as archive:
                self.assertIsNone(archive.testzip())
                names = set(archive.namelist())
            prefix = "DATA_PATUNG_downscaled"
            self.assertIn(f"{prefix}/Ganesha/IMG_000001.jpg", names)
            self.assertIn(f"{prefix}/Siwa/IMG_000001.jpg", names)
            self.assertIn(f"{prefix}/{BATCH_SUMMARY_FILENAME}", names)
            self.assertEqual(
                source_bytes,
                {
                    path.relative_to(source).as_posix(): path.read_bytes()
                    for path in source.rglob("*")
                    if path.is_file()
                },
            )

    def test_corrupt_image_blocks_entire_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            write_image(source / "Ganesha" / "good.jpg", 32, 18)
            broken = source / "Siwa" / "broken.jpg"
            broken.parent.mkdir(parents=True)
            broken.write_bytes(b"not an image")

            preflight = preflight_batch(
                source,
                {"Ganesha": "Ganesha", "Siwa": "Siwa"},
                root_name="DATA_PATUNG",
            )
            self.assertFalse(preflight.can_process)
            self.assertEqual(preflight.datasets[1].corrupt, 1)
            self.assertEqual(
                preflight.corrupt_images[0].relative_path, "Siwa/broken.jpg"
            )
            with self.assertRaisesRegex(BatchDownscaleError, "broken.jpg"):
                run_batch_downscale(
                    source,
                    root / "published",
                    {"Ganesha": "Ganesha", "Siwa": "Siwa"},
                    root_name="DATA_PATUNG",
                )
            self.assertFalse((root / "published").exists())

    def test_browser_paths_are_strict_and_dataset_names_are_sanitized(self) -> None:
        parsed = parse_browser_relative_path("Patung A/IMG_000001.jpg", "root")
        self.assertEqual(parsed.dataset_name, "Patung A")
        self.assertEqual(parsed.dataset_id, "Patung A")
        self.assertEqual(
            parse_browser_relative_path("IMG_000001.jpg", "single").filename,
            "IMG_000001.jpg",
        )
        self.assertEqual(sanitize_component("Patung:Siwa?"), "Patung_Siwa_")
        self.assertEqual(sanitize_component("CON"), "_CON")
        for unsafe in (
            "../escape.jpg",
            "/absolute.jpg",
            "C:/absolute.jpg",
            "A/nested/image.jpg",
            "A\\image.jpg",
        ):
            with self.subTest(path=unsafe):
                with self.assertRaises(BatchDownscaleError):
                    parse_browser_relative_path(unsafe, "root")

    def test_non_images_are_reported_and_377_image_dataset_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            for index in range(377):
                write_image(source / "Tualen" / f"IMG_{index:06d}.png", 2, 2)

            preflight = preflight_batch(
                source,
                {"Tualen": "Tualen"},
                root_name="DATA_PATUNG",
                ignored_files=("Tualen/notes.txt",),
            )

            self.assertEqual(preflight.total_images, 377)
            self.assertEqual(preflight.total_resize, 0)
            self.assertEqual(preflight.total_unchanged, 377)
            self.assertEqual(preflight.ignored_files, ("Tualen/notes.txt",))
            self.assertTrue(is_supported_image("x.JPG"))
            self.assertFalse(is_supported_image("notes.txt"))

    def test_full_hd_and_custom_resolution_reuse_existing_planner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source"
            write_image(source / "Durga" / "wide.jpg", 3840, 2160)
            names = {"Durga": "Durga"}

            full_hd = preflight_batch(source, names, root_name="root")
            custom = preflight_batch(
                source,
                names,
                root_name="root",
                max_width=1280,
                max_height=720,
            )

            self.assertEqual(
                (full_hd.datasets[0].resize, full_hd.max_width, full_hd.max_height),
                (1, 1920, 1080),
            )
            self.assertEqual((custom.max_width, custom.max_height), (1280, 720))


if __name__ == "__main__":
    unittest.main()
