import csv
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools.calibration.models import CalibrationError, DatasetSpec
from tools.pilot_labeling.runner import PilotConfig, prepare_pilot_packages


FIELDS = [
    "filename",
    "source_timestamp",
    "blur_score",
    "similarity_score",
    "duplicate_method",
    "compared_with",
]


class PilotLabelingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _dataset(self, dataset_id: str) -> tuple[DatasetSpec, Path]:
        rows = [{"filename": "ref.jpg", "source_timestamp": 0, "blur_score": 10}]
        for index in range(2):
            rows.append(
                {
                    "filename": f"ssim_{index}.jpg",
                    "source_timestamp": index + 1,
                    "blur_score": 20 + index,
                    "similarity_score": 0.8 + index * 0.1,
                    "duplicate_method": "SSIM",
                    "compared_with": "ref.jpg",
                }
            )
            rows.append(
                {
                    "filename": f"orb_{index}.jpg",
                    "source_timestamp": index + 3,
                    "blur_score": 30 + index,
                    "similarity_score": 0.6 + index * 0.1,
                    "duplicate_method": "ORB",
                    "compared_with": "ref.jpg",
                }
            )
        manifest = self.root / f"{dataset_id}_manifest.csv"
        with manifest.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        images = self.root / f"{dataset_id}_images"
        images.mkdir()
        for index, row in enumerate(rows):
            filename = row["filename"]
            Image.new(
                "RGB",
                (4, 4),
                ((index * 40) % 255, (index * 70) % 255, (index * 90) % 255),
            ).save(images / filename)
        return DatasetSpec(dataset_id, manifest), images

    def test_all_three_blind_packages_and_repeats_are_created(self) -> None:
        first, first_images = self._dataset("video_a")
        second, second_images = self._dataset("video_b")
        output = self.root / "pilot_labeling"
        selected = prepare_pilot_packages(
            PilotConfig(
                datasets=[first, second],
                image_roots={"video_a": first_images, "video_b": second_images},
                output_dir=output,
                blur_samples=4,
                ssim_samples=4,
                orb_samples=4,
                bins=2,
                seed=42,
                repeat_fraction=0.25,
            )
        )
        for method in ("blur", "ssim", "orb"):
            self.assertEqual(len(selected[method]), 4)
            package_csv = output / method / "candidates.csv"
            self.assertTrue(package_csv.is_file())
            header = package_csv.read_text(encoding="utf-8").splitlines()[0]
            self.assertNotIn("score", header)
            self.assertNotIn("status", header)
            repeat_csv = output / "pilot_consistency" / method / "candidates.csv"
            with repeat_csv.open(newline="", encoding="utf-8") as csv_file:
                self.assertEqual(len(list(csv.DictReader(csv_file))), 1)
        report = (output / "PILOT_PACKAGE_REPORT.md").read_text(encoding="utf-8")
        self.assertIn("Status: READY FOR MANUAL LABELING", report)
        self.assertIn("| BLUR | video_a |", report)
        self.assertTrue((output / "PILOT_LABELING_CHECKLIST.md").is_file())
        self.assertTrue((output / "PILOT_RESULTS.md").is_file())

    def test_missing_pair_image_fails_before_output_is_created(self) -> None:
        spec, images = self._dataset("video_a")
        (images / "ref.jpg").unlink()
        output = self.root / "pilot_labeling"
        with self.assertRaisesRegex(CalibrationError, "Image not found"):
            prepare_pilot_packages(
                PilotConfig(
                    datasets=[spec],
                    image_roots={"video_a": images},
                    output_dir=output,
                    blur_samples=1,
                    ssim_samples=1,
                    orb_samples=1,
                    bins=2,
                    repeat_fraction=0,
                )
            )
        self.assertFalse(output.exists())

    def test_method_dataset_filters_avoid_cross_run_duplication(self) -> None:
        first, first_images = self._dataset("video_ssim_run")
        second, second_images = self._dataset("video_orb_run")
        output = self.root / "pilot_labeling"
        selected = prepare_pilot_packages(
            PilotConfig(
                datasets=[first, second],
                image_roots={
                    "video_ssim_run": first_images,
                    "video_orb_run": second_images,
                },
                output_dir=output,
                blur_samples=2,
                ssim_samples=2,
                orb_samples=2,
                bins=2,
                repeat_fraction=0,
                method_dataset_ids={
                    "blur": ["video_ssim_run"],
                    "ssim": ["video_ssim_run"],
                    "orb": ["video_orb_run"],
                },
            )
        )
        self.assertEqual(
            {item.dataset_id for item in selected["blur"]}, {"video_ssim_run"}
        )
        self.assertEqual(
            {item.dataset_id for item in selected["ssim"]}, {"video_ssim_run"}
        )
        self.assertEqual(
            {item.dataset_id for item in selected["orb"]}, {"video_orb_run"}
        )
        report = (output / "PILOT_PACKAGE_REPORT.md").read_text(encoding="utf-8")
        self.assertIn("video_ssim_run", report)
        self.assertIn("BLUR, SSIM", report)

    def test_unreadable_image_fails_before_output_is_created(self) -> None:
        spec, images = self._dataset("video_a")
        (images / "ref.jpg").write_bytes(b"not-an-image")
        output = self.root / "pilot_labeling"
        with self.assertRaisesRegex(CalibrationError, "Unreadable image"):
            prepare_pilot_packages(
                PilotConfig(
                    datasets=[spec],
                    image_roots={"video_a": images},
                    output_dir=output,
                    blur_samples=5,
                    ssim_samples=1,
                    orb_samples=1,
                    bins=2,
                    repeat_fraction=0,
                )
            )
        self.assertFalse(output.exists())

    def test_blur_only_mode_does_not_create_duplicate_packages(self) -> None:
        spec, images = self._dataset("video_a")
        output = self.root / "pilot_labeling"
        selected = prepare_pilot_packages(
            PilotConfig(
                datasets=[spec],
                image_roots={"video_a": images},
                output_dir=output,
                blur_samples=5,
                bins=2,
                repeat_fraction=0.2,
                methods=["blur"],
            )
        )
        self.assertEqual(set(selected), {"blur"})
        self.assertTrue((output / "blur" / "candidates.csv").is_file())
        self.assertTrue(
            (output / "pilot_consistency" / "blur" / "candidates.csv").is_file()
        )
        self.assertFalse((output / "ssim").exists())
        self.assertFalse((output / "orb").exists())
        self.assertFalse((output / "DUPLICATE_LABELING_PROTOCOL.md").exists())


if __name__ == "__main__":
    unittest.main()
