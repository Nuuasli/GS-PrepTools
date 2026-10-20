import csv
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools.calibration.io import load_blur_labels, load_manifests
from tools.calibration.models import CalibrationError, DatasetSpec
from tools.calibration_sampling.package import create_labeling_package
from tools.calibration_sampling.sampling import (
    build_candidates,
    stratified_sample,
    write_candidate_csv,
)


FIELDS = [
    "filename",
    "source_timestamp",
    "blur_score",
    "similarity_score",
    "duplicate_method",
    "compared_with",
]


def write_manifest(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


class CalibrationSamplingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _blur_manifests(self, datasets: int = 2, rows: int = 20):
        specs = []
        for dataset_index in range(datasets):
            dataset_id = f"video_{dataset_index}"
            path = self.root / f"{dataset_id}_manifest.csv"
            write_manifest(
                path,
                [
                    {
                        "filename": f"frame_{index:03d}.jpg",
                        "source_timestamp": index / 2,
                        "blur_score": dataset_index * 100 + index,
                    }
                    for index in range(rows)
                ],
            )
            specs.append(DatasetSpec(dataset_id, path))
        return load_manifests(specs)

    def test_same_seed_is_deterministic_and_sample_count_is_exact(self) -> None:
        candidates = build_candidates(self._blur_manifests(), "blur")
        first = stratified_sample(
            candidates, sample_count=16, bins=4, seed=42
        )
        second = stratified_sample(
            candidates, sample_count=16, bins=4, seed=42
        )
        self.assertEqual([item.key for item in first], [item.key for item in second])
        self.assertEqual(len(first), 16)
        self.assertEqual(len({item.key for item in first}), 16)

    def test_quantile_bins_and_dataset_ids_are_represented(self) -> None:
        candidates = build_candidates(self._blur_manifests(), "blur")
        selected = stratified_sample(
            candidates, sample_count=16, bins=4, seed=11
        )
        by_dataset: dict[str, set[int]] = {}
        for item in selected:
            by_dataset.setdefault(item.dataset_id, set()).add(item.stratum)
        self.assertEqual(set(by_dataset), {"video_0", "video_1"})
        self.assertEqual(by_dataset["video_0"], {0, 1, 2, 3})
        self.assertEqual(by_dataset["video_1"], {0, 1, 2, 3})

    def test_samples_per_dataset_prevents_one_dataset_dominating(self) -> None:
        candidates = build_candidates(self._blur_manifests(), "blur")
        selected = stratified_sample(
            candidates,
            sample_count=10,
            bins=4,
            seed=42,
            samples_per_dataset=5,
        )
        counts = {
            dataset_id: sum(item.dataset_id == dataset_id for item in selected)
            for dataset_id in {item.dataset_id for item in selected}
        }
        self.assertEqual(counts, {"video_0": 5, "video_1": 5})

    def test_ssim_and_orb_are_not_mixed_and_pair_is_preserved(self) -> None:
        path = self.root / "pairs_manifest.csv"
        write_manifest(
            path,
            [
                {"filename": "ref.jpg", "blur_score": 100},
                {
                    "filename": "ssim.jpg",
                    "blur_score": 100,
                    "similarity_score": 0.95,
                    "duplicate_method": "SSIM",
                    "compared_with": "ref.jpg",
                },
                {
                    "filename": "orb.jpg",
                    "blur_score": 100,
                    "similarity_score": 0.70,
                    "duplicate_method": "ORB",
                    "compared_with": "ref.jpg",
                },
            ],
        )
        manifests = load_manifests([DatasetSpec("pairs", path)])
        ssim = build_candidates(manifests, "ssim")
        orb = build_candidates(manifests, "orb")
        self.assertEqual([(item.filename, item.compared_with) for item in ssim], [("ssim.jpg", "ref.jpg")])
        self.assertEqual([(item.filename, item.compared_with) for item in orb], [("orb.jpg", "ref.jpg")])

    def test_invalid_duplicate_pair_is_rejected(self) -> None:
        path = self.root / "invalid_manifest.csv"
        write_manifest(
            path,
            [
                {
                    "filename": "current.jpg",
                    "blur_score": 100,
                    "similarity_score": 0.9,
                    "duplicate_method": "SSIM",
                    "compared_with": "missing.jpg",
                }
            ],
        )
        manifests = load_manifests([DatasetSpec("invalid", path)])
        with self.assertRaisesRegex(CalibrationError, "missing from manifest"):
            build_candidates(manifests, "ssim")

    def test_blind_csv_hides_scores_and_keeps_label_fields(self) -> None:
        candidates = build_candidates(self._blur_manifests(1, 5), "blur")
        selected = stratified_sample(
            candidates, sample_count=3, bins=3, seed=42
        )
        output = self.root / "candidates.csv"
        write_candidate_csv(output, selected)
        with output.open(newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            rows = list(reader)
        self.assertNotIn("blur_score", reader.fieldnames or [])
        self.assertNotIn("source_timestamp", reader.fieldnames or [])
        self.assertEqual(
            set(reader.fieldnames or []),
            {"item_id", "dataset_id", "filename", "label", "annotator_id", "notes"},
        )
        self.assertTrue(all(row["dataset_id"] == "video_0" for row in rows))

        for row in rows:
            row["label"] = "sharp"
            row["annotator_id"] = "annotator_a"
            row["notes"] = "pilot"
        with output.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=reader.fieldnames or [])
            writer.writeheader()
            writer.writerows(rows)
        loaded, excluded = load_blur_labels(
            [output], self._blur_manifests(1, 5), ["video_0"], "error"
        )
        self.assertEqual(len(loaded), 3)
        self.assertEqual(excluded, 0)

    def test_blind_duplicate_package_copies_pair_without_modification(self) -> None:
        path = self.root / "pairs_manifest.csv"
        write_manifest(
            path,
            [
                {"filename": "ref.jpg", "blur_score": 100},
                {
                    "filename": "current.jpg",
                    "blur_score": 100,
                    "similarity_score": 0.9,
                    "duplicate_method": "SSIM",
                    "compared_with": "ref.jpg",
                },
            ],
        )
        images = self.root / "images"
        images.mkdir()
        Image.new("RGB", (4, 4), (255, 0, 0)).save(images / "ref.jpg")
        Image.new("RGB", (4, 4), (0, 255, 0)).save(images / "current.jpg")
        reference_bytes = (images / "ref.jpg").read_bytes()
        current_bytes = (images / "current.jpg").read_bytes()
        manifests = load_manifests([DatasetSpec("pairs", path)])
        candidates = build_candidates(manifests, "ssim")
        package = self.root / "package"
        create_labeling_package(
            package, candidates, {"pairs": images}, seed=42
        )
        pair = package / "pairs" / "item_0001"
        self.assertEqual((pair / "reference.jpg").read_bytes(), reference_bytes)
        self.assertEqual((pair / "current.jpg").read_bytes(), current_bytes)
        header = (package / "candidates.csv").read_text(encoding="utf-8").splitlines()[0]
        self.assertNotIn("similarity_score", header)
        self.assertIn("compared_with", header)


if __name__ == "__main__":
    unittest.main()
