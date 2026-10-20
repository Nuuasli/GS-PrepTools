import csv
import tempfile
import unittest
from pathlib import Path

from tools.calibration.io import (
    build_dataset_specs,
    load_blur_labels,
    load_duplicate_labels,
    load_manifests,
)
from tools.calibration.metrics import confusion_at_threshold, predict_positive
from tools.calibration.models import CalibrationError, DatasetSpec, LabeledScore
from tools.calibration.runner import CalibrationConfig, run_calibration


MANIFEST_FIELDS = [
    "filename",
    "blur_score",
    "similarity_score",
    "duplicate_method",
    "compared_with",
]


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class CalibrationMetricTests(unittest.TestCase):
    def test_blur_threshold_classification_and_metrics(self) -> None:
        samples = [
            LabeledScore("d", "a", 10, True, "blur"),
            LabeledScore("d", "b", 30, True, "blur"),
            LabeledScore("d", "c", 20, False, "sharp"),
            LabeledScore("d", "d", 40, False, "sharp"),
        ]
        matrix = confusion_at_threshold(samples, 25, "below")
        self.assertEqual((matrix.tp, matrix.fp, matrix.tn, matrix.fn), (1, 1, 1, 1))
        self.assertEqual(matrix.accuracy, 0.5)
        self.assertEqual(matrix.precision, 0.5)
        self.assertEqual(matrix.recall, 0.5)
        self.assertEqual(matrix.f1, 0.5)
        self.assertEqual(matrix.specificity, 0.5)
        self.assertEqual(matrix.false_positive_rate, 0.5)

    def test_duplicate_threshold_classification_and_metrics(self) -> None:
        samples = [
            LabeledScore("d", "a", 0.9, True, "duplicate"),
            LabeledScore("d", "b", 0.7, True, "duplicate"),
            LabeledScore("d", "c", 0.85, False, "keep"),
            LabeledScore("d", "d", 0.4, False, "keep"),
        ]
        matrix = confusion_at_threshold(samples, 0.8, "above_or_equal")
        self.assertEqual((matrix.tp, matrix.fp, matrix.tn, matrix.fn), (1, 1, 1, 1))
        self.assertTrue(predict_positive(0.8, 0.8, "above_or_equal"))
        self.assertFalse(predict_positive(25, 25, "below"))


class CalibrationInputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _manifest(self, name: str, rows: list[dict]) -> DatasetSpec:
        path = self.root / f"{name}_manifest.csv"
        write_csv(path, MANIFEST_FIELDS, rows)
        return DatasetSpec(name, path)

    def test_missing_labeled_filename_is_an_error(self) -> None:
        spec = self._manifest(
            "video", [{"filename": "a.jpg", "blur_score": "10"}]
        )
        labels = self.root / "blur.csv"
        write_csv(labels, ["filename", "label"], [{"filename": "x.jpg", "label": "blur"}])
        manifests = load_manifests([spec])
        with self.assertRaisesRegex(CalibrationError, "not found in manifest"):
            load_blur_labels([labels], manifests, ["video"], "error")

    def test_empty_duplicate_score_is_an_error(self) -> None:
        spec = self._manifest(
            "video",
            [
                {"filename": "a.jpg", "blur_score": "10"},
                {
                    "filename": "b.jpg",
                    "blur_score": "20",
                    "duplicate_method": "SSIM",
                    "compared_with": "a.jpg",
                },
            ],
        )
        labels = self.root / "duplicate.csv"
        write_csv(
            labels,
            ["filename", "compared_with", "label"],
            [{"filename": "b.jpg", "compared_with": "a.jpg", "label": "keep"}],
        )
        with self.assertRaisesRegex(CalibrationError, "Missing similarity_score"):
            load_duplicate_labels(
                [labels], load_manifests([spec]), ["video"]
            )

    def test_compared_with_mismatch_is_an_error(self) -> None:
        spec = self._manifest(
            "video",
            [
                {"filename": "a.jpg", "blur_score": "10"},
                {
                    "filename": "b.jpg",
                    "blur_score": "20",
                    "similarity_score": "0.8",
                    "duplicate_method": "ORB",
                    "compared_with": "a.jpg",
                },
            ],
        )
        labels = self.root / "duplicate.csv"
        write_csv(
            labels,
            ["filename", "compared_with", "label"],
            [{"filename": "b.jpg", "compared_with": "x.jpg", "label": "keep"}],
        )
        with self.assertRaisesRegex(CalibrationError, "compared_with mismatch"):
            load_duplicate_labels(
                [labels], load_manifests([spec]), ["video"]
            )

    def test_multiple_datasets_do_not_collide_on_filename(self) -> None:
        first = self._manifest(
            "first", [{"filename": "IMG_000001.jpg", "blur_score": "10"}]
        )
        second = self._manifest(
            "second", [{"filename": "IMG_000001.jpg", "blur_score": "100"}]
        )
        manifests = load_manifests([first, second])
        self.assertEqual(len(manifests), 2)
        self.assertEqual(manifests[("first", "IMG_000001.jpg")].blur_score, 10)
        self.assertEqual(manifests[("second", "IMG_000001.jpg")].blur_score, 100)

    def test_derived_dataset_id_collision_requires_explicit_ids(self) -> None:
        directory_a = self.root / "a"
        directory_b = self.root / "b"
        directory_a.mkdir()
        directory_b.mkdir()
        first = directory_a / "video_manifest.csv"
        second = directory_b / "video_manifest.csv"
        first.touch()
        second.touch()
        with self.assertRaisesRegex(CalibrationError, "Duplicate dataset ID"):
            build_dataset_specs([first, second], [])

    def test_ssim_and_orb_outputs_are_separate_and_files_are_written(self) -> None:
        spec = self._manifest(
            "video",
            [
                {"filename": "ref.jpg", "blur_score": "100"},
                {
                    "filename": "ssim.jpg",
                    "blur_score": "110",
                    "similarity_score": "0.95",
                    "duplicate_method": "SSIM",
                    "compared_with": "ref.jpg",
                },
                {
                    "filename": "orb.jpg",
                    "blur_score": "120",
                    "similarity_score": "0.75",
                    "duplicate_method": "ORB",
                    "compared_with": "ref.jpg",
                },
            ],
        )
        duplicate_labels = self.root / "duplicate.csv"
        write_csv(
            duplicate_labels,
            ["filename", "compared_with", "label"],
            [
                {"filename": "ssim.jpg", "compared_with": "ref.jpg", "label": "duplicate"},
                {"filename": "orb.jpg", "compared_with": "ref.jpg", "label": "keep"},
            ],
        )
        output = self.root / "output"
        analyses = run_calibration(
            CalibrationConfig(
                datasets=[spec],
                output_dir=output,
                duplicate_label_paths=[duplicate_labels],
                generate_plots=False,
            )
        )
        self.assertEqual(set(analyses), {"ssim", "orb"})
        self.assertEqual([sample.filename for sample in analyses["ssim"].samples], ["ssim.jpg"])
        self.assertEqual([sample.filename for sample in analyses["orb"].samples], ["orb.jpg"])
        for method in ("ssim", "orb"):
            self.assertTrue((output / method / "threshold_analysis.csv").exists())
            self.assertTrue((output / method / "misclassified_frames.csv").exists())
            self.assertTrue((output / method / "summary.json").exists())
        self.assertTrue((output / "calibration_summary.md").exists())

    def test_plot_artifacts_are_written(self) -> None:
        spec = self._manifest(
            "video",
            [
                {"filename": "blur.jpg", "blur_score": "10"},
                {"filename": "sharp.jpg", "blur_score": "100"},
            ],
        )
        labels = self.root / "blur.csv"
        write_csv(
            labels,
            ["filename", "label"],
            [
                {"filename": "blur.jpg", "label": "blur"},
                {"filename": "sharp.jpg", "label": "sharp"},
            ],
        )
        output = self.root / "output"
        run_calibration(
            CalibrationConfig(
                datasets=[spec],
                output_dir=output,
                blur_label_paths=[labels],
            )
        )
        for filename in (
            "score_distribution.png",
            "threshold_metrics.png",
            "confusion_matrix.png",
        ):
            artifact = output / "blur" / filename
            self.assertTrue(artifact.exists())
            self.assertGreater(artifact.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
