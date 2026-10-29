"""CLI for standalone downscaling of already-extracted image folders."""

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from tools.image_downscale.runner import DownscaleError, run_downscale


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _jpeg_quality(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 100:
        raise argparse.ArgumentTypeError("JPEG quality must be between 1 and 100")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Downscale an existing extracted-image folder into a new folder. "
            "Original images are never modified."
        )
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-width", type=_positive_int, default=1920)
    parser.add_argument("--max-height", type=_positive_int, default=1080)
    parser.add_argument(
        "--jpeg-quality",
        type=_jpeg_quality,
        default=100,
        help="JPEG encode quality for resized JPEG files (default: 100).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Deliberately overwrite matching output images and manifest.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print the plan without writing any files.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = run_downscale(
            args.input,
            args.output,
            max_width=args.max_width,
            max_height=args.max_height,
            jpeg_quality=args.jpeg_quality,
            force=args.force,
            dry_run=args.dry_run,
        )
    except (DownscaleError, OSError, ValueError) as exc:
        print(f"Image downscale error: {exc}", file=sys.stderr)
        return 2

    if summary.dry_run:
        print("DRY RUN - no files written")
    else:
        print(f"Output: {summary.output_dir}")
    print(f"Images: {summary.image_count}")
    print(f"Will resize: {summary.resized_count}")
    print(f"Unchanged: {summary.unchanged_count}")
    for plan in summary.plans:
        print(
            f"- {plan.filename}: "
            f"{plan.source_width}x{plan.source_height} -> "
            f"{plan.output_width}x{plan.output_height} [{plan.status}]"
        )
    if summary.manifest_path:
        print(f"Manifest: {summary.manifest_path}")
    return 0
