"""Batch orchestration for the standalone image downscale utility.

This module intentionally delegates every image transformation to
``tools.image_downscale.run_downscale``.  It only handles dataset discovery,
preflight aggregation, folder-preserving output, summaries, and archives.
"""

from __future__ import annotations

import csv
import os
import re
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Optional, Sequence

from tools.image_downscale.runner import (
    DownscaleError,
    SUPPORTED_EXTENSIONS,
    inspect_image_plan,
    preflight_downscale,
    run_downscale,
)


BATCH_SUMMARY_FILENAME = "batch_downscale_summary.csv"
BATCH_SUMMARY_FIELDS = (
    "dataset_id",
    "input_images",
    "resized_images",
    "unchanged_images",
    "output_images",
    "failed_images",
    "max_width",
    "max_height",
    "status",
)
_INVALID_COMPONENT = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class BatchDownscaleError(DownscaleError):
    """Raised when a batch cannot be safely preflighted or completed."""


@dataclass(frozen=True)
class UploadPath:
    """Validated browser-relative upload identity."""

    dataset_name: str
    dataset_id: str
    filename: str
    relative_path: str


@dataclass(frozen=True)
class CorruptImage:
    dataset_name: str
    dataset_id: str
    relative_path: str
    error: str


@dataclass(frozen=True)
class DatasetPreflight:
    dataset_name: str
    dataset_id: str
    images: int
    resize: int
    unchanged: int
    corrupt: int


@dataclass(frozen=True)
class BatchPreflight:
    root_name: str
    root_id: str
    datasets: tuple[DatasetPreflight, ...]
    corrupt_images: tuple[CorruptImage, ...]
    ignored_files: tuple[str, ...]
    max_width: int
    max_height: int

    @property
    def dataset_count(self) -> int:
        return len(self.datasets)

    @property
    def total_images(self) -> int:
        return sum(dataset.images for dataset in self.datasets)

    @property
    def total_resize(self) -> int:
        return sum(dataset.resize for dataset in self.datasets)

    @property
    def total_unchanged(self) -> int:
        return sum(dataset.unchanged for dataset in self.datasets)

    @property
    def can_process(self) -> bool:
        return not self.corrupt_images and bool(self.datasets)


@dataclass(frozen=True)
class BatchDatasetResult:
    dataset_name: str
    dataset_id: str
    input_images: int
    resized_images: int
    unchanged_images: int
    output_images: int
    failed_images: int
    status: str


@dataclass(frozen=True)
class BatchResult:
    root_name: str
    root_id: str
    output_root: Path
    archive_path: Optional[Path]
    summary_path: Path
    datasets: tuple[BatchDatasetResult, ...]

    @property
    def total_images(self) -> int:
        return sum(dataset.input_images for dataset in self.datasets)

    @property
    def resized_images(self) -> int:
        return sum(dataset.resized_images for dataset in self.datasets)

    @property
    def unchanged_images(self) -> int:
        return sum(dataset.unchanged_images for dataset in self.datasets)

    @property
    def output_images(self) -> int:
        return sum(dataset.output_images for dataset in self.datasets)

    @property
    def failed_images(self) -> int:
        return sum(dataset.failed_images for dataset in self.datasets)


@dataclass(frozen=True)
class LocalPathLayout:
    """Validated direct-filesystem dataset root used by trusted localhost mode."""

    input_root: Path
    output_root: Path
    dataset_names: dict[str, str]
    dataset_sources: dict[str, Path]
    ignored_files: tuple[str, ...]


@dataclass(frozen=True)
class QuickSamplePlan:
    filename: str
    source_width: Optional[int]
    source_height: Optional[int]
    output_width: Optional[int]
    output_height: Optional[int]
    action: str
    error: Optional[str] = None


@dataclass(frozen=True)
class QuickDatasetPreflight:
    dataset_name: str
    dataset_id: str
    total_images: int
    samples: tuple[QuickSamplePlan, ...]

    @property
    def sampled_count(self) -> int:
        return len(self.samples)

    @property
    def sample_errors(self) -> int:
        return sum(sample.error is not None for sample in self.samples)

    @property
    def sampled_resize(self) -> int:
        return sum(sample.action == "resize" for sample in self.samples)

    @property
    def sampled_unchanged(self) -> int:
        return sum(sample.action == "unchanged" for sample in self.samples)


@dataclass(frozen=True)
class QuickBatchPreflight:
    root_name: str
    input_root: Path
    output_root: Path
    datasets: tuple[QuickDatasetPreflight, ...]
    ignored_files: tuple[str, ...]
    samples_per_dataset: int
    max_width: int
    max_height: int

    @property
    def dataset_count(self) -> int:
        return len(self.datasets)

    @property
    def total_images(self) -> int:
        return sum(dataset.total_images for dataset in self.datasets)

    @property
    def total_sampled(self) -> int:
        return sum(dataset.sampled_count for dataset in self.datasets)

    @property
    def total_sample_errors(self) -> int:
        return sum(dataset.sample_errors for dataset in self.datasets)

    @property
    def can_process(self) -> bool:
        return self.total_sample_errors == 0


def sanitize_component(value: str, *, fallback: str = "dataset") -> str:
    """Return a deterministic Windows-safe filesystem/archive component."""
    normalized = " ".join(value.strip().split())
    normalized = _INVALID_COMPONENT.sub("_", normalized).rstrip(" .")
    if not normalized:
        normalized = fallback
    if normalized.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        normalized = f"_{normalized}"
    return normalized[:120].rstrip(" .") or fallback


def _validate_filename(filename: str) -> None:
    if (
        not filename
        or filename in {".", ".."}
        or filename.rstrip(" .") != filename
        or _INVALID_COMPONENT.search(filename)
        or filename.split(".", 1)[0].upper() in _WINDOWS_RESERVED
    ):
        raise BatchDownscaleError(f"Unsafe image filename: {filename!r}")


def parse_browser_relative_path(relative_path: str, input_mode: str) -> UploadPath:
    """Validate an untrusted relative path without consulting the local filesystem.

    The frontend removes the common directory-picker root.  Root mode therefore
    accepts exactly ``dataset/image``; single mode accepts exactly ``image``.
    Deeper nesting is deliberately rejected instead of flattened.
    """
    if input_mode not in {"single", "root"}:
        raise BatchDownscaleError(f"Unsupported input mode: {input_mode}")
    parts = validate_browser_relative_path(relative_path)

    required_parts = 1 if input_mode == "single" else 2
    if len(parts) != required_parts:
        structure = "image" if input_mode == "single" else "dataset/image"
        raise BatchDownscaleError(
            f"Nested directories are not supported; expected {structure}: "
            f"{relative_path}"
        )

    if input_mode == "single":
        dataset_name = "dataset"
        filename = parts[0]
    else:
        dataset_name, filename = parts
        if dataset_name.rstrip(" .") != dataset_name:
            raise BatchDownscaleError(f"Unsafe dataset name: {dataset_name!r}")

    _validate_filename(filename)
    dataset_id = sanitize_component(dataset_name)
    return UploadPath(dataset_name, dataset_id, filename, relative_path)


def validate_browser_relative_path(relative_path: str) -> tuple[str, ...]:
    """Reject absolute, traversal, drive-prefixed, and ambiguous browser paths."""
    if not relative_path or "\\" in relative_path or "\x00" in relative_path:
        raise BatchDownscaleError(f"Unsafe relative path: {relative_path!r}")
    if relative_path.startswith("/") or re.match(r"^[A-Za-z]:", relative_path):
        raise BatchDownscaleError(f"Absolute paths are not allowed: {relative_path}")

    parts = tuple(relative_path.split("/"))
    if any(part in {"", ".", ".."} for part in parts):
        raise BatchDownscaleError(f"Path traversal is not allowed: {relative_path}")

    return parts


def preflight_batch(
    source_root: Path,
    dataset_names: Mapping[str, str],
    *,
    root_name: str,
    max_width: int = 1920,
    max_height: int = 1080,
    ignored_files: Sequence[str] = (),
    dataset_sources: Optional[Mapping[str, Path]] = None,
) -> BatchPreflight:
    """Inspect every dataset without writing final images."""
    if max_width <= 0 or max_height <= 0:
        raise BatchDownscaleError("Maximum dimensions must be greater than zero")
    root_id = sanitize_component(root_name, fallback="image_dataset")
    datasets: list[DatasetPreflight] = []
    corrupt_images: list[CorruptImage] = []

    for dataset_id in sorted(dataset_names, key=lambda value: value.casefold()):
        dataset_name = dataset_names[dataset_id]
        input_dir = (
            dataset_sources[dataset_id]
            if dataset_sources is not None
            else source_root / dataset_id
        )
        planned_output = source_root.parent / "planned" / dataset_id
        inspection = preflight_downscale(
            input_dir,
            planned_output,
            max_width=max_width,
            max_height=max_height,
        )
        datasets.append(
            DatasetPreflight(
                dataset_name=dataset_name,
                dataset_id=dataset_id,
                images=inspection.image_count,
                resize=inspection.resized_count,
                unchanged=inspection.unchanged_count,
                corrupt=len(inspection.issues),
            )
        )
        corrupt_images.extend(
            CorruptImage(
                dataset_name=dataset_name,
                dataset_id=dataset_id,
                relative_path=f"{dataset_name}/{issue.filename}",
                error=issue.error,
            )
            for issue in inspection.issues
        )

    if not datasets:
        raise BatchDownscaleError("No datasets containing supported images were found")
    return BatchPreflight(
        root_name=root_name,
        root_id=root_id,
        datasets=tuple(datasets),
        corrupt_images=tuple(corrupt_images),
        ignored_files=tuple(sorted(ignored_files, key=str.casefold)),
        max_width=max_width,
        max_height=max_height,
    )


def inspect_local_dataset_root(input_path: str, output_path: str) -> LocalPathLayout:
    """Validate and discover a direct local dataset root without writing files."""
    if not input_path.strip() or not output_path.strip():
        raise BatchDownscaleError("Input and output paths are required")
    input_root = Path(input_path).expanduser().resolve()
    output_root = Path(output_path).expanduser().resolve()
    if not input_root.exists():
        raise BatchDownscaleError(f"Input path does not exist: {input_root}")
    if not input_root.is_dir():
        raise BatchDownscaleError(f"Input path is not a directory: {input_root}")
    if not os.access(input_root, os.R_OK):
        raise BatchDownscaleError(f"Input path is not readable: {input_root}")
    if input_root == output_root:
        raise BatchDownscaleError("Output path must be different from input path")
    if output_root.is_relative_to(input_root):
        raise BatchDownscaleError("Output path cannot be inside the input path")
    if output_root.exists():
        raise BatchDownscaleError(f"Output path already exists: {output_root}")

    writable_parent = output_root.parent
    while not writable_parent.exists() and writable_parent != writable_parent.parent:
        writable_parent = writable_parent.parent
    if not writable_parent.is_dir() or not os.access(writable_parent, os.W_OK):
        raise BatchDownscaleError(
            f"Output parent is not writable: {writable_parent}"
        )

    dataset_names: dict[str, str] = {}
    dataset_sources: dict[str, Path] = {}
    ignored_files: list[str] = []
    for root_file in sorted(input_root.iterdir(), key=lambda item: item.name.casefold()):
        if root_file.is_file():
            relative = root_file.relative_to(input_root).as_posix()
            if root_file.suffix.lower() in SUPPORTED_EXTENSIONS:
                raise BatchDownscaleError(
                    f"Images must be inside top-level dataset folders: {relative}"
                )
            ignored_files.append(relative)
            continue
        if not root_file.is_dir():
            continue

        dataset_name = root_file.name
        dataset_id = sanitize_component(dataset_name)
        existing = dataset_names.get(dataset_id)
        if existing is not None and existing != dataset_name:
            raise BatchDownscaleError(
                "Dataset names collide after filesystem sanitization: "
                f"{existing!r} and {dataset_name!r}"
            )

        supported = []
        for candidate in sorted(
            root_file.rglob("*"),
            key=lambda item: item.relative_to(input_root).as_posix().casefold(),
        ):
            if not candidate.is_file():
                continue
            relative = candidate.relative_to(input_root).as_posix()
            if candidate.suffix.lower() not in SUPPORTED_EXTENSIONS:
                ignored_files.append(relative)
                continue
            if candidate.parent != root_file:
                raise BatchDownscaleError(
                    "Nested image directories are not supported: " f"{relative}"
                )
            supported.append(candidate)

        if supported:
            dataset_names[dataset_id] = dataset_name
            dataset_sources[dataset_id] = root_file

    if not dataset_names:
        raise BatchDownscaleError("No datasets containing supported images were found")
    return LocalPathLayout(
        input_root=input_root,
        output_root=output_root,
        dataset_names=dataset_names,
        dataset_sources=dataset_sources,
        ignored_files=tuple(ignored_files),
    )


def _deterministic_sample(images: Sequence[Path], count: int) -> list[Path]:
    if count <= 0:
        raise BatchDownscaleError("Samples per dataset must be a positive integer")
    if count >= len(images):
        return list(images)
    if count == 1:
        return [images[0]]
    indices = [round(index * (len(images) - 1) / (count - 1)) for index in range(count)]
    return [images[index] for index in indices]


def quick_preflight_local(
    layout: LocalPathLayout,
    *,
    samples_per_dataset: int = 2,
    max_width: int = 1920,
    max_height: int = 1080,
) -> QuickBatchPreflight:
    """Inspect deterministic samples while counting every supported filename."""
    if samples_per_dataset <= 0:
        raise BatchDownscaleError("Samples per dataset must be a positive integer")
    datasets: list[QuickDatasetPreflight] = []
    for dataset_id in sorted(layout.dataset_names, key=str.casefold):
        dataset_name = layout.dataset_names[dataset_id]
        source_dir = layout.dataset_sources[dataset_id]
        images = sorted(
            (
                path
                for path in source_dir.iterdir()
                if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
            ),
            key=lambda path: (path.name.casefold(), path.name),
        )
        samples: list[QuickSamplePlan] = []
        for source_path in _deterministic_sample(images, samples_per_dataset):
            try:
                plan = inspect_image_plan(
                    source_path,
                    layout.output_root / dataset_id / source_path.name,
                    max_width=max_width,
                    max_height=max_height,
                )
            except DownscaleError as exc:
                samples.append(
                    QuickSamplePlan(
                        filename=source_path.name,
                        source_width=None,
                        source_height=None,
                        output_width=None,
                        output_height=None,
                        action="error",
                        error=str(exc),
                    )
                )
                continue
            samples.append(
                QuickSamplePlan(
                    filename=source_path.name,
                    source_width=plan.source_width,
                    source_height=plan.source_height,
                    output_width=plan.output_width,
                    output_height=plan.output_height,
                    action="resize" if plan.resized else "unchanged",
                )
            )
        datasets.append(
            QuickDatasetPreflight(
                dataset_name=dataset_name,
                dataset_id=dataset_id,
                total_images=len(images),
                samples=tuple(samples),
            )
        )
    return QuickBatchPreflight(
        root_name=layout.input_root.name,
        input_root=layout.input_root,
        output_root=layout.output_root,
        datasets=tuple(datasets),
        ignored_files=layout.ignored_files,
        samples_per_dataset=samples_per_dataset,
        max_width=max_width,
        max_height=max_height,
    )


def _write_batch_summary(
    path: Path,
    datasets: Sequence[BatchDatasetResult],
    max_width: int,
    max_height: int,
) -> None:
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=BATCH_SUMMARY_FIELDS)
        writer.writeheader()
        for dataset in datasets:
            writer.writerow(
                {
                    "dataset_id": dataset.dataset_id,
                    "input_images": dataset.input_images,
                    "resized_images": dataset.resized_images,
                    "unchanged_images": dataset.unchanged_images,
                    "output_images": dataset.output_images,
                    "failed_images": dataset.failed_images,
                    "max_width": max_width,
                    "max_height": max_height,
                    "status": dataset.status,
                }
            )


def _create_and_validate_zip(source_root: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(
            source_root.rglob("*"),
            key=lambda item: item.relative_to(source_root.parent).as_posix().casefold(),
        ):
            if path.is_file():
                archive.write(path, path.relative_to(source_root.parent).as_posix())
    with zipfile.ZipFile(destination, "r") as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise BatchDownscaleError(f"ZIP validation failed: {bad_member}")


def run_batch_downscale(
    source_root: Path,
    output_parent: Path,
    dataset_names: Mapping[str, str],
    *,
    root_name: str,
    max_width: int = 1920,
    max_height: int = 1080,
    jpeg_quality: int = 100,
    single_folder: bool = False,
    dataset_sources: Optional[Mapping[str, Path]] = None,
    direct_output_root: Optional[Path] = None,
    create_archive: bool = True,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> BatchResult:
    """Sequentially process a clean batch and atomically publish final output."""
    preflight = preflight_batch(
        source_root,
        dataset_names,
        root_name=root_name,
        max_width=max_width,
        max_height=max_height,
        dataset_sources=dataset_sources,
    )
    if preflight.corrupt_images:
        first = preflight.corrupt_images[0]
        raise BatchDownscaleError(
            f"Batch blocked by corrupt image: {first.relative_path}: {first.error}"
        )
    if single_folder and len(preflight.datasets) != 1:
        raise BatchDownscaleError("Single-folder mode requires exactly one dataset")

    if direct_output_root is not None:
        final_root = direct_output_root.expanduser().resolve()
        output_parent = final_root.parent
        output_name = final_root.name
    else:
        output_name = f"{preflight.root_id}_downscaled"
        final_root = output_parent / output_name
    output_parent.mkdir(parents=True, exist_ok=True)
    final_archive = (
        output_parent / f"{preflight.root_id}_downscaled_{max_width}x{max_height}.zip"
        if create_archive
        else None
    )
    if final_root.exists() or (final_archive is not None and final_archive.exists()):
        raise BatchDownscaleError("Final batch output already exists")

    staging_container = output_parent / f".{output_name}.staging-{uuid.uuid4().hex}"
    staged_root = staging_container / output_name
    temp_archive = (
        output_parent / f".{final_archive.name}.{uuid.uuid4().hex}.tmp"
        if final_archive is not None
        else None
    )
    results: list[BatchDatasetResult] = []
    published_root = False
    try:
        staged_root.mkdir(parents=True)
        total = len(preflight.datasets)
        for index, dataset in enumerate(preflight.datasets, start=1):
            if progress:
                progress(index, total, dataset.dataset_name)
            dataset_output = (
                staged_root if single_folder else staged_root / dataset.dataset_id
            )
            dataset_input = (
                dataset_sources[dataset.dataset_id]
                if dataset_sources is not None
                else source_root / dataset.dataset_id
            )
            summary = run_downscale(
                dataset_input,
                dataset_output,
                max_width=max_width,
                max_height=max_height,
                jpeg_quality=jpeg_quality,
            )
            output_images = summary.resized_count + summary.unchanged_count
            if output_images != summary.image_count:
                raise BatchDownscaleError(
                    f"Dataset output invariant failed: {dataset.dataset_name}"
                )
            results.append(
                BatchDatasetResult(
                    dataset_name=dataset.dataset_name,
                    dataset_id=dataset.dataset_id,
                    input_images=summary.image_count,
                    resized_images=summary.resized_count,
                    unchanged_images=summary.unchanged_count,
                    output_images=output_images,
                    failed_images=0,
                    status="completed",
                )
            )

        summary_path = staged_root / BATCH_SUMMARY_FILENAME
        _write_batch_summary(summary_path, results, max_width, max_height)
        if temp_archive is not None:
            _create_and_validate_zip(staged_root, temp_archive)

        os.replace(staged_root, final_root)
        published_root = True
        if temp_archive is not None and final_archive is not None:
            os.replace(temp_archive, final_archive)
        return BatchResult(
            root_name=root_name,
            root_id=preflight.root_id,
            output_root=final_root,
            archive_path=final_archive,
            summary_path=final_root / BATCH_SUMMARY_FILENAME,
            datasets=tuple(results),
        )
    except BaseException:
        if published_root:
            shutil.rmtree(final_root, ignore_errors=True)
        if final_archive is not None:
            final_archive.unlink(missing_ok=True)
        raise
    finally:
        if temp_archive is not None:
            temp_archive.unlink(missing_ok=True)
        shutil.rmtree(staging_container, ignore_errors=True)


def is_supported_image(path: str) -> bool:
    """Return whether a browser-relative filename uses a supported extension."""
    return PurePosixPath(path).suffix.lower() in SUPPORTED_EXTENSIONS
