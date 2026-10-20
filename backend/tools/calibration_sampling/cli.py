"""CLI for reproducible calibration candidate selection and packaging."""

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, Optional, Sequence

from tools.calibration.io import build_dataset_specs, load_manifests
from tools.calibration.models import CalibrationError
from tools.calibration_sampling.package import create_labeling_package
from tools.calibration_sampling.sampling import (
    build_candidates,
    stratified_sample,
    write_candidate_csv,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Select reproducible, score-stratified manual-label candidates. "
            "Blind CSV output hides algorithm scores by default."
        )
    )
    parser.add_argument("--manifest", action="append", type=Path, default=[])
    parser.add_argument(
        "--dataset",
        action="append",
        default=[],
        metavar="DATASET_ID=PATH",
        help="Manifest with explicit dataset ID; repeat for multiple videos.",
    )
    parser.add_argument("--type", required=True, choices=["blur", "ssim", "orb"])
    parser.add_argument("--samples", type=int, default=150)
    parser.add_argument("--bins", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--samples-per-dataset",
        type=int,
        help="Optional maximum number selected from any one dataset.",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--include-scores",
        action="store_true",
        help="Create a non-blind audit CSV containing algorithm scores.",
    )
    parser.add_argument(
        "--package-dir",
        type=Path,
        help="Optional blind offline package; requires --images-root mappings.",
    )
    parser.add_argument(
        "--images-root",
        action="append",
        default=[],
        metavar="DATASET_ID=PATH",
        help="Image directory for one dataset; repeat for multiple datasets.",
    )
    return parser


def _image_roots(values: Sequence[str]) -> Dict[str, Path]:
    mappings: Dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise CalibrationError(
                f"Invalid --images-root '{value}'. Expected DATASET_ID=PATH"
            )
        dataset_id, raw_path = value.split("=", 1)
        dataset_id = dataset_id.strip()
        root = Path(raw_path.strip()).resolve()
        if not dataset_id or not raw_path.strip():
            raise CalibrationError(
                f"Invalid --images-root '{value}'. Expected DATASET_ID=PATH"
            )
        if dataset_id in mappings:
            raise CalibrationError(f"Duplicate images root for {dataset_id}")
        if not root.is_dir():
            raise CalibrationError(f"Images root not found: {root}")
        mappings[dataset_id] = root
    return mappings


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        specs = build_dataset_specs(args.manifest, args.dataset)
        manifests = load_manifests(specs)
        eligible = build_candidates(manifests, args.type)
        selected = stratified_sample(
            eligible,
            sample_count=args.samples,
            bins=args.bins,
            seed=args.seed,
            samples_per_dataset=args.samples_per_dataset,
        )
        output = args.output.resolve()
        if args.package_dir:
            package_dir = args.package_dir.resolve()
            if output == package_dir or output.is_relative_to(package_dir):
                raise CalibrationError(
                    "--output must be outside --package-dir; the package writes "
                    "its own blind candidates.csv"
                )
            create_labeling_package(
                package_dir,
                selected,
                _image_roots(args.images_root),
                seed=args.seed,
            )
        write_candidate_csv(
            output, selected, include_scores=args.include_scores
        )
    except (CalibrationError, OSError, ValueError) as exc:
        print(f"Sampling error: {exc}", file=sys.stderr)
        return 2

    counts = Counter(candidate.dataset_id for candidate in selected)
    print(f"Wrote {len(selected)} {args.type.upper()} candidates to: {output}")
    print(f"Seed: {args.seed}; bins per dataset: {args.bins}")
    for dataset_id in sorted(counts):
        print(f"- {dataset_id}: {counts[dataset_id]}")
    if args.package_dir:
        print(f"Blind labeling package: {args.package_dir.resolve()}")
    return 0
