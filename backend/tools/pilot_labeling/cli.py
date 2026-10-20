"""CLI entry point for preparing blur, SSIM, and ORB pilot packages."""

import argparse
import sys
from pathlib import Path
from typing import Dict, Optional, Sequence

from tools.calibration.io import build_dataset_specs
from tools.calibration.models import CalibrationError
from tools.pilot_labeling.runner import PilotConfig, prepare_pilot_packages


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare validated blind pilot packages for blur, SSIM, and ORB. "
            "This command does not run calibration analysis."
        )
    )
    parser.add_argument("--manifest", action="append", type=Path, default=[])
    parser.add_argument(
        "--dataset", action="append", default=[], metavar="DATASET_ID=PATH"
    )
    parser.add_argument(
        "--images-root",
        action="append",
        default=[],
        required=True,
        metavar="DATASET_ID=PATH",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--method",
        action="append",
        choices=["blur", "ssim", "orb"],
        default=[],
        help="Pilot method to prepare; repeat as needed. Defaults to all methods.",
    )
    parser.add_argument("--blur-samples", type=int, default=60)
    parser.add_argument("--ssim-samples", type=int, default=60)
    parser.add_argument("--orb-samples", type=int, default=60)
    parser.add_argument("--bins", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--samples-per-dataset", type=int)
    parser.add_argument("--repeat-fraction", type=float, default=0.1)
    parser.add_argument(
        "--source-video",
        action="append",
        default=[],
        metavar="DATASET_ID=SOURCE_VIDEO_ID",
        help="Map separate method runs back to one physical source video.",
    )
    for method in ("blur", "ssim", "orb"):
        parser.add_argument(
            f"--{method}-dataset-id",
            action="append",
            default=[],
            help=(
                f"Restrict {method.upper()} sampling to this dataset ID; "
                "repeat as needed."
            ),
        )
    return parser


def _parse_image_roots(values: Sequence[str]) -> Dict[str, Path]:
    mappings: Dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise CalibrationError(
                f"Invalid --images-root '{value}'. Expected DATASET_ID=PATH"
            )
        dataset_id, raw_path = value.split("=", 1)
        dataset_id = dataset_id.strip()
        raw_path = raw_path.strip()
        if not dataset_id or not raw_path:
            raise CalibrationError(
                f"Invalid --images-root '{value}'. Expected DATASET_ID=PATH"
            )
        root = Path(raw_path).resolve()
        if dataset_id in mappings:
            raise CalibrationError(f"Duplicate images root for {dataset_id}")
        if not root.is_dir():
            raise CalibrationError(f"Images root not found: {root}")
        mappings[dataset_id] = root
    return mappings


def _parse_source_videos(values: Sequence[str]) -> Dict[str, str]:
    mappings: Dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise CalibrationError(
                f"Invalid --source-video '{value}'. Expected DATASET_ID=SOURCE_VIDEO_ID"
            )
        dataset_id, source_video_id = (part.strip() for part in value.split("=", 1))
        if not dataset_id or not source_video_id:
            raise CalibrationError(
                f"Invalid --source-video '{value}'. Expected DATASET_ID=SOURCE_VIDEO_ID"
            )
        if dataset_id in mappings:
            raise CalibrationError(f"Duplicate source-video mapping for {dataset_id}")
        mappings[dataset_id] = source_video_id
    return mappings


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        datasets = build_dataset_specs(args.manifest, args.dataset)
        config = PilotConfig(
            datasets=datasets,
            image_roots=_parse_image_roots(args.images_root),
            output_dir=args.output.resolve(),
            blur_samples=args.blur_samples,
            ssim_samples=args.ssim_samples,
            orb_samples=args.orb_samples,
            bins=args.bins,
            seed=args.seed,
            samples_per_dataset=args.samples_per_dataset,
            repeat_fraction=args.repeat_fraction,
            method_dataset_ids={
                method: getattr(args, f"{method}_dataset_id")
                for method in ("blur", "ssim", "orb")
                if getattr(args, f"{method}_dataset_id")
            },
            source_video_ids=_parse_source_videos(args.source_video),
            methods=args.method or ["blur", "ssim", "orb"],
        )
        selected = prepare_pilot_packages(config)
    except (CalibrationError, OSError, ValueError) as exc:
        print(f"Pilot preparation error: {exc}", file=sys.stderr)
        return 2

    print(f"Pilot packages ready: {config.output_dir}")
    print(f"Calibration datasets: {len(config.datasets)}")
    print(f"Seed: {config.seed}; bins: {config.bins}")
    for method in config.methods:
        print(f"- {method.upper()}: {len(selected[method])} candidates")
    print(f"Report: {config.output_dir / 'PILOT_PACKAGE_REPORT.md'}")
    print("Stop for manual labeling; calibration analysis was not run.")
    return 0
