"""CSV loading and strict cross-file validation for calibration inputs."""

import csv
import math
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from tools.calibration.models import (
    CalibrationError,
    DatasetSpec,
    LabeledScore,
    ManifestRow,
)


MANIFEST_REQUIRED_FIELDS = {
    "filename",
    "blur_score",
    "similarity_score",
    "duplicate_method",
    "compared_with",
}


def derive_dataset_id(manifest_path: Path) -> str:
    dataset_id = manifest_path.stem
    for suffix in ("_manifest", "-manifest"):
        if dataset_id.lower().endswith(suffix):
            dataset_id = dataset_id[: -len(suffix)]
            break
    if not dataset_id:
        raise CalibrationError(f"Could not derive dataset ID from {manifest_path}")
    return dataset_id


def build_dataset_specs(
    manifests: Iterable[Path], explicit_datasets: Iterable[str]
) -> List[DatasetSpec]:
    specs = [
        DatasetSpec(derive_dataset_id(path), path.resolve()) for path in manifests
    ]
    for value in explicit_datasets:
        if "=" not in value:
            raise CalibrationError(
                f"Invalid --dataset value '{value}'. Expected DATASET_ID=PATH"
            )
        dataset_id, raw_path = value.split("=", 1)
        dataset_id = dataset_id.strip()
        if not dataset_id or not raw_path.strip():
            raise CalibrationError(
                f"Invalid --dataset value '{value}'. Expected DATASET_ID=PATH"
            )
        specs.append(DatasetSpec(dataset_id, Path(raw_path).resolve()))

    if not specs:
        raise CalibrationError("At least one --manifest or --dataset is required")
    seen_ids: set[str] = set()
    for spec in specs:
        if spec.dataset_id in seen_ids:
            raise CalibrationError(f"Duplicate dataset ID: {spec.dataset_id}")
        seen_ids.add(spec.dataset_id)
        if not spec.manifest_path.is_file():
            raise CalibrationError(f"Manifest not found: {spec.manifest_path}")
    return specs


def _optional_float(value: Optional[str], context: str) -> Optional[float]:
    if value is None or not value.strip():
        return None
    try:
        parsed = float(value)
    except ValueError as exc:
        raise CalibrationError(f"Invalid numeric value for {context}: {value}") from exc
    if not math.isfinite(parsed):
        raise CalibrationError(f"Non-finite numeric value for {context}: {value}")
    return parsed


def load_manifests(specs: Iterable[DatasetSpec]) -> Dict[Tuple[str, str], ManifestRow]:
    records: Dict[Tuple[str, str], ManifestRow] = {}
    for spec in specs:
        with spec.manifest_path.open(newline="", encoding="utf-8-sig") as csv_file:
            reader = csv.DictReader(csv_file)
            fields = set(reader.fieldnames or [])
            missing_fields = MANIFEST_REQUIRED_FIELDS - fields
            if missing_fields:
                raise CalibrationError(
                    f"Manifest {spec.manifest_path} is missing fields: "
                    f"{', '.join(sorted(missing_fields))}"
                )
            row_count = 0
            for line_number, row in enumerate(reader, start=2):
                row_count += 1
                filename = (row.get("filename") or "").strip()
                if not filename:
                    raise CalibrationError(
                        f"Empty filename in {spec.manifest_path}:{line_number}"
                    )
                key = (spec.dataset_id, filename)
                if key in records:
                    raise CalibrationError(
                        f"Ambiguous duplicate filename in dataset {spec.dataset_id}: "
                        f"{filename}"
                    )
                method = (row.get("duplicate_method") or "").strip().upper() or None
                if method not in (None, "SSIM", "ORB"):
                    raise CalibrationError(
                        f"Invalid duplicate_method '{method}' for "
                        f"{spec.dataset_id}/{filename}"
                    )
                records[key] = ManifestRow(
                    dataset_id=spec.dataset_id,
                    filename=filename,
                    blur_score=_optional_float(
                        row.get("blur_score"),
                        f"blur_score at {spec.manifest_path}:{line_number}",
                    ),
                    similarity_score=_optional_float(
                        row.get("similarity_score"),
                        f"similarity_score at {spec.manifest_path}:{line_number}",
                    ),
                    duplicate_method=method,
                    compared_with=(row.get("compared_with") or "").strip() or None,
                    source_timestamp=_optional_float(
                        row.get("source_timestamp"),
                        f"source_timestamp at {spec.manifest_path}:{line_number}",
                    ),
                )
            if row_count == 0:
                raise CalibrationError(f"Manifest is empty: {spec.manifest_path}")
    return records


def _resolve_dataset_id(
    row: dict,
    dataset_ids: List[str],
    label_path: Path,
    line_number: int,
) -> str:
    dataset_id = (row.get("dataset_id") or "").strip()
    if dataset_id:
        if dataset_id not in dataset_ids:
            raise CalibrationError(
                f"Unknown dataset_id '{dataset_id}' at {label_path}:{line_number}"
            )
        return dataset_id
    if len(dataset_ids) == 1:
        return dataset_ids[0]
    raise CalibrationError(
        f"dataset_id is required at {label_path}:{line_number} when using "
        "multiple manifests"
    )


def load_blur_labels(
    label_paths: Iterable[Path],
    manifests: Dict[Tuple[str, str], ManifestRow],
    dataset_ids: List[str],
    borderline_policy: str,
) -> tuple[List[LabeledScore], int]:
    samples: List[LabeledScore] = []
    seen: set[Tuple[str, str]] = set()
    excluded_borderline = 0
    valid_labels = {"sharp", "blur", "borderline"}

    for label_path in label_paths:
        if not label_path.is_file():
            raise CalibrationError(f"Blur label file not found: {label_path}")
        with label_path.open(newline="", encoding="utf-8-sig") as csv_file:
            reader = csv.DictReader(csv_file)
            required = {"filename", "label"}
            if not required.issubset(set(reader.fieldnames or [])):
                raise CalibrationError(
                    f"Blur labels {label_path} require columns: filename,label"
                )
            for line_number, row in enumerate(reader, start=2):
                dataset_id = _resolve_dataset_id(
                    row, dataset_ids, label_path, line_number
                )
                filename = (row.get("filename") or "").strip()
                label = (row.get("label") or "").strip().lower()
                if label not in valid_labels:
                    raise CalibrationError(
                        f"Invalid blur label '{label}' at {label_path}:{line_number}"
                    )
                key = (dataset_id, filename)
                if key in seen:
                    raise CalibrationError(
                        f"Duplicate blur label for {dataset_id}/{filename}"
                    )
                seen.add(key)
                manifest = manifests.get(key)
                if not manifest:
                    raise CalibrationError(
                        f"Blur label not found in manifest: {dataset_id}/{filename}"
                    )
                if manifest.blur_score is None:
                    raise CalibrationError(
                        f"Missing blur_score for labeled frame: {dataset_id}/{filename}"
                    )
                if label == "borderline":
                    if borderline_policy == "error":
                        raise CalibrationError(
                            f"Borderline label at {label_path}:{line_number}; choose "
                            "--borderline-policy exclude, blur, or sharp"
                        )
                    if borderline_policy == "exclude":
                        excluded_borderline += 1
                        continue
                    label = borderline_policy
                samples.append(
                    LabeledScore(
                        dataset_id=dataset_id,
                        filename=filename,
                        score=manifest.blur_score,
                        is_positive=label == "blur",
                        true_label=label,
                    )
                )
    if not samples:
        raise CalibrationError("No usable manual blur labels were loaded")
    return samples, excluded_borderline


def load_duplicate_labels(
    label_paths: Iterable[Path],
    manifests: Dict[Tuple[str, str], ManifestRow],
    dataset_ids: List[str],
) -> Dict[str, List[LabeledScore]]:
    samples: Dict[str, List[LabeledScore]] = {"SSIM": [], "ORB": []}
    seen: set[Tuple[str, str]] = set()

    for label_path in label_paths:
        if not label_path.is_file():
            raise CalibrationError(f"Duplicate label file not found: {label_path}")
        with label_path.open(newline="", encoding="utf-8-sig") as csv_file:
            reader = csv.DictReader(csv_file)
            required = {"filename", "compared_with", "label"}
            if not required.issubset(set(reader.fieldnames or [])):
                raise CalibrationError(
                    f"Duplicate labels {label_path} require columns: "
                    "filename,compared_with,label"
                )
            for line_number, row in enumerate(reader, start=2):
                dataset_id = _resolve_dataset_id(
                    row, dataset_ids, label_path, line_number
                )
                filename = (row.get("filename") or "").strip()
                compared_with = (row.get("compared_with") or "").strip()
                label = (row.get("label") or "").strip().lower()
                if label not in {"duplicate", "keep"}:
                    raise CalibrationError(
                        f"Invalid duplicate label '{label}' at "
                        f"{label_path}:{line_number}"
                    )
                key = (dataset_id, filename)
                if key in seen:
                    raise CalibrationError(
                        f"Ambiguous duplicate label for {dataset_id}/{filename}"
                    )
                seen.add(key)
                manifest = manifests.get(key)
                if not manifest:
                    raise CalibrationError(
                        f"Duplicate label not found in manifest: {dataset_id}/{filename}"
                    )
                if not manifest.compared_with:
                    raise CalibrationError(
                        f"Frame was never compared by duplicate detector: "
                        f"{dataset_id}/{filename}"
                    )
                if compared_with != manifest.compared_with:
                    raise CalibrationError(
                        f"compared_with mismatch for {dataset_id}/{filename}: label "
                        f"has '{compared_with}', manifest has '{manifest.compared_with}'"
                    )
                reference_key = (dataset_id, compared_with)
                if reference_key not in manifests:
                    raise CalibrationError(
                        f"Compared frame is missing from manifest: "
                        f"{dataset_id}/{compared_with}"
                    )
                if not manifest.duplicate_method:
                    raise CalibrationError(
                        f"Missing duplicate_method for {dataset_id}/{filename}"
                    )
                if manifest.similarity_score is None:
                    raise CalibrationError(
                        f"Missing similarity_score for {dataset_id}/{filename}"
                    )
                samples[manifest.duplicate_method].append(
                    LabeledScore(
                        dataset_id=dataset_id,
                        filename=filename,
                        score=manifest.similarity_score,
                        is_positive=label == "duplicate",
                        true_label=label,
                        compared_with=compared_with,
                    )
                )

    if not samples["SSIM"] and not samples["ORB"]:
        raise CalibrationError("No usable manual duplicate labels were loaded")
    return samples
