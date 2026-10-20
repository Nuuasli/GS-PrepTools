"""Command-line interface for offline threshold calibration."""

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from tools.calibration.io import build_dataset_specs
from tools.calibration.models import CalibrationError
from tools.calibration.runner import CalibrationConfig, SweepRange, run_calibration


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze GS-Prep manifest scores against manual labels. This utility "
            "does not modify runtime pipeline thresholds."
        )
    )
    parser.add_argument(
        "--manifest",
        action="append",
        type=Path,
        default=[],
        help="Manifest path; repeat for multiple datasets. Dataset ID is derived from filename.",
    )
    parser.add_argument(
        "--dataset",
        action="append",
        default=[],
        metavar="DATASET_ID=PATH",
        help="Manifest with an explicit dataset ID; repeat as needed.",
    )
    parser.add_argument(
        "--blur-labels",
        action="append",
        type=Path,
        default=[],
        help="Manual blur label CSV; repeat to combine files.",
    )
    parser.add_argument(
        "--duplicate-labels",
        action="append",
        type=Path,
        default=[],
        help="Manual duplicate label CSV; repeat to combine files.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--borderline-policy",
        choices=["error", "exclude", "blur", "sharp"],
        default="error",
        help="Explicit handling for optional blur label 'borderline'.",
    )
    parser.add_argument("--target-recall", type=float, default=0.9)
    parser.add_argument(
        "--no-plots",
        action="store_true",
        help="Skip PNG generation (matplotlib is then not required).",
    )
    for prefix in ("blur", "ssim", "orb"):
        parser.add_argument(f"--{prefix}-min", type=float)
        parser.add_argument(f"--{prefix}-max", type=float)
        parser.add_argument(f"--{prefix}-step", type=float)
    return parser


def _range_from_args(args: argparse.Namespace, prefix: str) -> SweepRange:
    return SweepRange(
        minimum=getattr(args, f"{prefix}_min"),
        maximum=getattr(args, f"{prefix}_max"),
        step=getattr(args, f"{prefix}_step"),
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        datasets = build_dataset_specs(args.manifest, args.dataset)
        analyses = run_calibration(
            CalibrationConfig(
                datasets=datasets,
                output_dir=args.output.resolve(),
                blur_label_paths=[path.resolve() for path in args.blur_labels],
                duplicate_label_paths=[
                    path.resolve() for path in args.duplicate_labels
                ],
                borderline_policy=args.borderline_policy,
                target_recall=args.target_recall,
                generate_plots=not args.no_plots,
                blur_range=_range_from_args(args, "blur"),
                ssim_range=_range_from_args(args, "ssim"),
                orb_range=_range_from_args(args, "orb"),
            )
        )
    except (CalibrationError, ValueError) as exc:
        print(f"Calibration error: {exc}", file=sys.stderr)
        return 2

    print(f"Calibration artifacts written to: {args.output.resolve()}")
    for name, result in analyses.items():
        print(
            f"- {name}: {len(result.samples)} samples, "
            f"{len(result.thresholds)} candidate thresholds"
        )
    return 0
