"""Safe, deterministic image-folder downscaling independent of the runtime pipeline."""

import csv
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import cv2
from PIL import Image


SUPPORTED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png"})
MANIFEST_FILENAME = "downscale_manifest.csv"
MANIFEST_FIELDS = (
    "filename",
    "source_width",
    "source_height",
    "output_width",
    "output_height",
    "resized",
    "source_size_bytes",
    "output_size_bytes",
)


class DownscaleError(ValueError):
    """Raised when preflight or downscale processing cannot complete safely."""


@dataclass(frozen=True)
class ImagePlan:
    source_path: Path
    output_path: Path
    source_width: int
    source_height: int
    output_width: int
    output_height: int
    source_size_bytes: int
    resized: bool

    @property
    def filename(self) -> str:
        return self.source_path.name

    @property
    def status(self) -> str:
        """Human-readable classification without changing manifest compatibility."""
        return "resized" if self.resized else "unchanged"


@dataclass(frozen=True)
class ImageIssue:
    """One unreadable input discovered during a non-writing preflight."""

    source_path: Path
    error: str

    @property
    def filename(self) -> str:
        return self.source_path.name


@dataclass(frozen=True)
class DownscalePreflight:
    """Complete inspection result, including valid plans and corrupt inputs."""

    input_dir: Path
    output_dir: Path
    plans: tuple[ImagePlan, ...]
    issues: tuple[ImageIssue, ...]

    @property
    def image_count(self) -> int:
        return len(self.plans) + len(self.issues)

    @property
    def resized_count(self) -> int:
        return sum(plan.resized for plan in self.plans)

    @property
    def unchanged_count(self) -> int:
        return len(self.plans) - self.resized_count


@dataclass(frozen=True)
class DownscaleSummary:
    input_dir: Path
    output_dir: Path
    plans: tuple[ImagePlan, ...]
    manifest_path: Optional[Path]
    dry_run: bool

    @property
    def image_count(self) -> int:
        return len(self.plans)

    @property
    def resized_count(self) -> int:
        return sum(plan.resized for plan in self.plans)

    @property
    def unchanged_count(self) -> int:
        return self.image_count - self.resized_count


def calculate_output_dimensions(
    source_width: int,
    source_height: int,
    max_width: int,
    max_height: int,
) -> tuple[int, int]:
    """Fit dimensions inside a bounding box without cropping or upscaling."""
    if source_width <= 0 or source_height <= 0:
        raise DownscaleError(
            f"Invalid source dimensions: {source_width}x{source_height}"
        )
    if max_width <= 0 or max_height <= 0:
        raise DownscaleError(
            f"Maximum dimensions must be positive: {max_width}x{max_height}"
        )

    # The target is a maximum bounding box, not an exact target size.
    # Returning the source dimensions here also guarantees no upscaling.
    if source_width <= max_width and source_height <= max_height:
        return source_width, source_height

    scale = min(max_width / source_width, max_height / source_height)
    output_width = min(max_width, max(1, round(source_width * scale)))
    output_height = min(max_height, max(1, round(source_height * scale)))
    return output_width, output_height


def _discover_images(input_dir: Path) -> list[Path]:
    images = [
        path
        for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    return sorted(images, key=lambda path: (path.name.casefold(), path.name))


def inspect_image_plan(
    source_path: Path,
    output_path: Path,
    *,
    max_width: int = 1920,
    max_height: int = 1080,
) -> ImagePlan:
    """Inspect one image and build its plan without writing output."""
    try:
        with Image.open(source_path) as source_image:
            source_width, source_height = source_image.size
            source_image.verify()
    except (OSError, ValueError) as exc:
        raise DownscaleError(str(exc) or "unreadable image") from exc
    if source_width <= 0 or source_height <= 0:
        raise DownscaleError(
            f"invalid dimensions {source_width}x{source_height}"
        )
    output_width, output_height = calculate_output_dimensions(
        source_width,
        source_height,
        max_width,
        max_height,
    )
    return ImagePlan(
        source_path=source_path,
        output_path=output_path,
        source_width=source_width,
        source_height=source_height,
        output_width=output_width,
        output_height=output_height,
        source_size_bytes=source_path.stat().st_size,
        resized=(output_width, output_height) != (source_width, source_height),
    )


def _inspect_plans(
    input_dir: Path,
    output_dir: Path,
    max_width: int,
    max_height: int,
) -> DownscalePreflight:
    image_paths = _discover_images(input_dir)
    if not image_paths:
        extensions = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise DownscaleError(
            f"No supported images found in {input_dir}; expected: {extensions}"
        )

    plans: list[ImagePlan] = []
    issues: list[ImageIssue] = []
    for source_path in image_paths:
        try:
            plan = inspect_image_plan(
                source_path,
                output_dir / source_path.name,
                max_width=max_width,
                max_height=max_height,
            )
        except DownscaleError as exc:
            issues.append(ImageIssue(source_path, str(exc) or "unreadable image"))
            continue
        plans.append(plan)

    return DownscalePreflight(
        input_dir=input_dir,
        output_dir=output_dir,
        plans=tuple(plans),
        issues=tuple(issues),
    )


def _validate_paths(input_dir: Path, output_dir: Path) -> None:
    if not input_dir.is_dir():
        raise DownscaleError(f"Input directory does not exist: {input_dir}")
    if input_dir == output_dir:
        raise DownscaleError("Output directory must be different from input directory")
    if output_dir.exists() and not output_dir.is_dir():
        raise DownscaleError(f"Output path is not a directory: {output_dir}")


def preflight_downscale(
    input_dir: Path,
    output_dir: Path,
    *,
    max_width: int = 1920,
    max_height: int = 1080,
) -> DownscalePreflight:
    """Inspect one folder without writing output, including corrupt-image details."""
    input_root = input_dir.expanduser().resolve()
    output_root = output_dir.expanduser().resolve()
    _validate_paths(input_root, output_root)
    return _inspect_plans(input_root, output_root, max_width, max_height)


def _validate_collisions(
    plans: Sequence[ImagePlan], output_dir: Path, force: bool
) -> None:
    if force:
        return
    collisions = [plan.output_path.name for plan in plans if plan.output_path.exists()]
    manifest_path = output_dir / MANIFEST_FILENAME
    if manifest_path.exists():
        collisions.append(MANIFEST_FILENAME)
    if collisions:
        names = ", ".join(collisions[:10])
        remainder = len(collisions) - 10
        suffix = f" (+{remainder} more)" if remainder > 0 else ""
        raise DownscaleError(
            f"Output files already exist: {names}{suffix}. Use --force to overwrite."
        )


def _temporary_path(destination: Path) -> Path:
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    return Path(raw_path)


def _commit_temp_file(temp_path: Path, destination: Path, force: bool) -> None:
    if destination.exists() and not force:
        raise DownscaleError(
            f"Output file appeared during processing: {destination.name}. "
            "Use --force to overwrite."
        )
    os.replace(temp_path, destination)


def _copy_unchanged(source: Path, destination: Path, force: bool) -> None:
    temp_path = _temporary_path(destination)
    try:
        shutil.copy2(source, temp_path)
        _commit_temp_file(temp_path, destination, force)
    finally:
        temp_path.unlink(missing_ok=True)


def _encode_resized(
    plan: ImagePlan,
    destination: Path,
    jpeg_quality: int,
    force: bool,
) -> None:
    image = cv2.imread(str(plan.source_path), cv2.IMREAD_UNCHANGED)
    if image is None or image.shape[:2] != (
        plan.source_height,
        plan.source_width,
    ):
        raise DownscaleError(
            f"Source image changed or became unreadable: {plan.source_path.name}"
        )

    resized = cv2.resize(
        image,
        (plan.output_width, plan.output_height),
        interpolation=cv2.INTER_AREA,
    )
    extension = plan.source_path.suffix.lower()
    if extension in {".jpg", ".jpeg"}:
        encoder_extension = ".jpg"
        parameters = [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]
    else:
        encoder_extension = ".png"
        parameters = [cv2.IMWRITE_PNG_COMPRESSION, 3]

    encoded, buffer = cv2.imencode(encoder_extension, resized, parameters)
    if not encoded:
        raise DownscaleError(f"Could not encode image: {plan.source_path.name}")

    temp_path = _temporary_path(destination)
    try:
        temp_path.write_bytes(buffer.tobytes())
        _commit_temp_file(temp_path, destination, force)
    finally:
        temp_path.unlink(missing_ok=True)


def _write_manifest(
    output_dir: Path,
    plans: Sequence[ImagePlan],
    force: bool,
) -> Path:
    manifest_path = output_dir / MANIFEST_FILENAME
    temp_path = _temporary_path(manifest_path)
    try:
        with temp_path.open("w", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=MANIFEST_FIELDS)
            writer.writeheader()
            for plan in plans:
                writer.writerow(
                    {
                        "filename": plan.filename,
                        "source_width": plan.source_width,
                        "source_height": plan.source_height,
                        "output_width": plan.output_width,
                        "output_height": plan.output_height,
                        "resized": str(plan.resized).lower(),
                        "source_size_bytes": plan.source_size_bytes,
                        "output_size_bytes": plan.output_path.stat().st_size,
                    }
                )
        _commit_temp_file(temp_path, manifest_path, force)
    finally:
        temp_path.unlink(missing_ok=True)
    return manifest_path


def run_downscale(
    input_dir: Path,
    output_dir: Path,
    *,
    max_width: int = 1920,
    max_height: int = 1080,
    jpeg_quality: int = 100,
    force: bool = False,
    dry_run: bool = False,
) -> DownscaleSummary:
    """Preflight and optionally downscale one deterministic image folder."""
    input_root = input_dir.expanduser().resolve()
    output_root = output_dir.expanduser().resolve()
    _validate_paths(input_root, output_root)
    if not 1 <= jpeg_quality <= 100:
        raise DownscaleError("JPEG quality must be between 1 and 100")

    preflight = _inspect_plans(input_root, output_root, max_width, max_height)
    if preflight.issues:
        details = ", ".join(issue.filename for issue in preflight.issues)
        raise DownscaleError(f"Unreadable or corrupt images: {details}")
    plans = preflight.plans
    if dry_run:
        return DownscaleSummary(
            input_dir=input_root,
            output_dir=output_root,
            plans=plans,
            manifest_path=None,
            dry_run=True,
        )

    _validate_collisions(plans, output_root, force)
    output_root.mkdir(parents=True, exist_ok=True)
    for plan in plans:
        if plan.resized:
            _encode_resized(plan, plan.output_path, jpeg_quality, force)
        else:
            _copy_unchanged(plan.source_path, plan.output_path, force)

    manifest_path = _write_manifest(output_root, plans, force)
    return DownscaleSummary(
        input_dir=input_root,
        output_dir=output_root,
        plans=plans,
        manifest_path=manifest_path,
        dry_run=False,
    )
