"""Create blind offline labeling packages without modifying source images."""

import hashlib
import shutil
from pathlib import Path
from typing import Dict, List, Tuple

from PIL import Image, UnidentifiedImageError

from tools.calibration.models import CalibrationError
from tools.calibration_sampling.sampling import (
    SamplingCandidate,
    write_candidate_csv,
)


def _source_image(root: Path, filename: str) -> Path:
    resolved_root = root.resolve()
    source = (resolved_root / filename).resolve()
    if not source.is_relative_to(resolved_root):
        raise CalibrationError(f"Image path escapes images root: {filename}")
    if not source.is_file():
        raise CalibrationError(f"Image not found: {source}")
    try:
        with Image.open(source) as image:
            image.verify()
    except (OSError, SyntaxError, UnidentifiedImageError) as exc:
        raise CalibrationError(f"Unreadable image: {source}") from exc
    return source


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _instructions(sample_type: str, seed: int) -> str:
    if sample_type == "blur":
        decision = (
            "Inspect each image without consulting algorithm scores. Use `sharp`, "
            "`blur`, or `borderline` according to BLUR_LABELING_PROTOCOL.md."
        )
        location = "Images are stored in `images/` using the matching item ID."
    else:
        decision = (
            "Compare `reference` against `current`. Use `duplicate` only when the "
            "current frame adds no meaningful visual/viewpoint information; "
            "otherwise use `keep`."
        )
        location = (
            "Each pair is stored in `pairs/<item_id>/` as `reference.*` and "
            "`current.*`."
        )
    return "\n".join(
        [
            "# Blind Labeling Package",
            "",
            f"Sampling seed: `{seed}`",
            "",
            decision,
            "",
            location,
            "",
            "Fill only `label`, `annotator_id`, and optional `notes` in candidates.csv.",
            "Do not look up scores, rejection reasons, thresholds, or previous labels while annotating.",
            "Do not edit the image files.",
            "",
        ]
    )


def validate_image_sources(
    candidates: List[SamplingCandidate], image_roots: Dict[str, Path]
) -> None:
    """Validate every current/reference image before package output is created."""
    if not candidates:
        raise CalibrationError("Cannot validate an empty candidate list")
    sample_types = {candidate.sample_type for candidate in candidates}
    if len(sample_types) != 1:
        raise CalibrationError("Labeling package cannot mix sample types")
    sample_type = next(iter(sample_types))
    for candidate in candidates:
        root = image_roots.get(candidate.dataset_id)
        if root is None:
            raise CalibrationError(
                f"Missing --images-root for dataset {candidate.dataset_id}"
            )
        _source_image(root, candidate.filename)
        if sample_type != "blur":
            if not candidate.compared_with:
                raise CalibrationError(
                    f"Missing compared_with for {candidate.dataset_id}/{candidate.filename}"
                )
            _source_image(root, candidate.compared_with)


def create_labeling_package(
    package_dir: Path,
    candidates: List[SamplingCandidate],
    image_roots: Dict[str, Path],
    *,
    seed: int,
) -> None:
    if not candidates:
        raise CalibrationError("Cannot package an empty candidate list")
    sample_types = {candidate.sample_type for candidate in candidates}
    if len(sample_types) != 1:
        raise CalibrationError("Labeling package cannot mix sample types")
    sample_type = next(iter(sample_types))

    if package_dir.exists() and any(package_dir.iterdir()):
        raise CalibrationError(f"Package directory is not empty: {package_dir}")

    validate_image_sources(candidates, image_roots)

    plans: List[Tuple[Path, Path]] = []
    for index, candidate in enumerate(candidates, start=1):
        root = image_roots.get(candidate.dataset_id)
        if root is None:
            raise CalibrationError(
                f"Missing --images-root for dataset {candidate.dataset_id}"
            )
        item_id = f"item_{index:04d}"
        current = _source_image(root, candidate.filename)
        if sample_type == "blur":
            destination = package_dir / "images" / f"{item_id}{current.suffix}"
            plans.append((current, destination))
        else:
            if not candidate.compared_with:
                raise CalibrationError(
                    f"Missing compared_with for {candidate.dataset_id}/{candidate.filename}"
                )
            reference = _source_image(root, candidate.compared_with)
            pair_dir = package_dir / "pairs" / item_id
            plans.extend(
                [
                    (reference, pair_dir / f"reference{reference.suffix}"),
                    (current, pair_dir / f"current{current.suffix}"),
                ]
            )

    package_dir.mkdir(parents=True, exist_ok=True)
    write_candidate_csv(
        package_dir / "candidates.csv", candidates, include_scores=False
    )
    (package_dir / "instructions.md").write_text(
        _instructions(sample_type, seed), encoding="utf-8"
    )
    for source, destination in plans:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if _sha256(source) != _sha256(destination):
            raise CalibrationError(
                f"Image integrity check failed after copy: {source} -> {destination}"
            )
