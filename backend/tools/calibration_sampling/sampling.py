"""Sampling logic and CSV output for blind manual-label preparation."""

import csv
import random
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from tools.calibration.models import CalibrationError, ManifestRow


@dataclass(frozen=True)
class SamplingCandidate:
    dataset_id: str
    filename: str
    score: float
    sample_type: str
    compared_with: Optional[str] = None
    source_timestamp: Optional[float] = None
    stratum: int = -1

    @property
    def key(self) -> Tuple[str, str, Optional[str]]:
        return (self.dataset_id, self.filename, self.compared_with)


def build_candidates(
    manifests: Dict[Tuple[str, str], ManifestRow], sample_type: str
) -> List[SamplingCandidate]:
    normalized_type = sample_type.lower()
    if normalized_type not in {"blur", "ssim", "orb"}:
        raise CalibrationError(f"Unsupported sample type: {sample_type}")

    candidates: List[SamplingCandidate] = []
    rows = sorted(
        manifests.values(), key=lambda row: (row.dataset_id, row.filename)
    )
    for row in rows:
        if normalized_type == "blur":
            if row.blur_score is None:
                raise CalibrationError(
                    f"Missing blur_score for {row.dataset_id}/{row.filename}"
                )
            candidates.append(
                SamplingCandidate(
                    dataset_id=row.dataset_id,
                    filename=row.filename,
                    score=row.blur_score,
                    sample_type="blur",
                    source_timestamp=row.source_timestamp,
                )
            )
            continue

        requested_method = normalized_type.upper()
        if row.duplicate_method != requested_method:
            continue
        if row.similarity_score is None:
            raise CalibrationError(
                f"Missing similarity_score for {row.dataset_id}/{row.filename}"
            )
        if not row.compared_with:
            raise CalibrationError(
                f"Missing compared_with for {row.dataset_id}/{row.filename}"
            )
        if (row.dataset_id, row.compared_with) not in manifests:
            raise CalibrationError(
                "Compared frame is missing from manifest: "
                f"{row.dataset_id}/{row.compared_with}"
            )
        candidates.append(
            SamplingCandidate(
                dataset_id=row.dataset_id,
                filename=row.filename,
                score=row.similarity_score,
                sample_type=normalized_type,
                compared_with=row.compared_with,
                source_timestamp=row.source_timestamp,
            )
        )

    if not candidates:
        raise CalibrationError(
            f"No eligible {normalized_type.upper()} candidates were found"
        )
    return candidates


def _allocate_dataset_quotas(
    capacities: Dict[str, int], sample_count: int, rng: random.Random
) -> Dict[str, int]:
    if sample_count <= 0:
        raise CalibrationError("Sample count must be greater than zero")
    total_capacity = sum(capacities.values())
    if sample_count > total_capacity:
        raise CalibrationError(
            f"Requested {sample_count} samples but only {total_capacity} are "
            "available after per-dataset limits"
        )

    dataset_order = sorted(capacities)
    rng.shuffle(dataset_order)
    priority = {dataset_id: index for index, dataset_id in enumerate(dataset_order)}
    quotas = {dataset_id: 0 for dataset_id in capacities}
    for _ in range(sample_count):
        eligible = [
            dataset_id
            for dataset_id, capacity in capacities.items()
            if quotas[dataset_id] < capacity
        ]
        chosen = min(
            eligible,
            key=lambda dataset_id: (quotas[dataset_id], priority[dataset_id]),
        )
        quotas[chosen] += 1
    return quotas


def _assign_quantile_strata(
    candidates: List[SamplingCandidate], bins: int
) -> List[SamplingCandidate]:
    ordered = sorted(
        candidates,
        key=lambda item: (item.score, item.filename, item.compared_with or ""),
    )
    count = len(ordered)
    return [
        replace(item, stratum=min(bins - 1, index * bins // count))
        for index, item in enumerate(ordered)
    ]


def _sample_one_dataset(
    candidates: List[SamplingCandidate], quota: int, bins: int, rng: random.Random
) -> List[SamplingCandidate]:
    stratified = _assign_quantile_strata(candidates, bins)
    by_stratum: Dict[int, List[SamplingCandidate]] = {}
    for candidate in stratified:
        by_stratum.setdefault(candidate.stratum, []).append(candidate)
    for values in by_stratum.values():
        rng.shuffle(values)

    stratum_order = sorted(by_stratum)
    rng.shuffle(stratum_order)
    selected: List[SamplingCandidate] = []
    while len(selected) < quota:
        made_progress = False
        for stratum in stratum_order:
            values = by_stratum[stratum]
            if values and len(selected) < quota:
                selected.append(values.pop())
                made_progress = True
        if not made_progress:
            raise CalibrationError("Unable to satisfy stratified sample quota")
    return selected


def stratified_sample(
    candidates: Iterable[SamplingCandidate],
    *,
    sample_count: int,
    bins: int,
    seed: int,
    samples_per_dataset: Optional[int] = None,
) -> List[SamplingCandidate]:
    if bins <= 0:
        raise CalibrationError("Bin count must be greater than zero")
    if samples_per_dataset is not None and samples_per_dataset <= 0:
        raise CalibrationError("samples-per-dataset must be greater than zero")

    by_dataset: Dict[str, List[SamplingCandidate]] = {}
    seen: set[Tuple[str, str, Optional[str]]] = set()
    for candidate in candidates:
        if candidate.key in seen:
            raise CalibrationError(
                "Duplicate candidate row: "
                f"{candidate.dataset_id}/{candidate.filename}"
            )
        seen.add(candidate.key)
        by_dataset.setdefault(candidate.dataset_id, []).append(candidate)
    if not by_dataset:
        raise CalibrationError("No candidates are available for sampling")

    capacities = {
        dataset_id: min(
            len(values),
            samples_per_dataset
            if samples_per_dataset is not None
            else len(values),
        )
        for dataset_id, values in by_dataset.items()
    }
    rng = random.Random(seed)
    quotas = _allocate_dataset_quotas(capacities, sample_count, rng)
    selected: List[SamplingCandidate] = []
    for dataset_id in sorted(by_dataset):
        quota = quotas[dataset_id]
        if quota:
            selected.extend(
                _sample_one_dataset(by_dataset[dataset_id], quota, bins, rng)
            )
    rng.shuffle(selected)
    return selected


def candidate_fieldnames(sample_type: str, include_scores: bool) -> List[str]:
    if sample_type == "blur":
        fields = ["item_id", "dataset_id", "filename"]
        if include_scores:
            fields.extend(["source_timestamp", "blur_score"])
    else:
        fields = ["item_id", "dataset_id", "filename", "compared_with"]
        if include_scores:
            fields.extend(["similarity_score", "duplicate_method"])
    fields.extend(["label", "annotator_id", "notes"])
    return fields


def candidate_rows(
    candidates: Iterable[SamplingCandidate], include_scores: bool
) -> List[dict]:
    rows = []
    for index, candidate in enumerate(candidates, start=1):
        row = {
            "item_id": f"item_{index:04d}",
            "dataset_id": candidate.dataset_id,
            "filename": candidate.filename,
            "label": "",
            "annotator_id": "",
            "notes": "",
        }
        if candidate.sample_type == "blur":
            if include_scores:
                row["source_timestamp"] = (
                    "" if candidate.source_timestamp is None else candidate.source_timestamp
                )
                row["blur_score"] = candidate.score
        else:
            row["compared_with"] = candidate.compared_with or ""
            if include_scores:
                row["similarity_score"] = candidate.score
                row["duplicate_method"] = candidate.sample_type.upper()
        rows.append(row)
    return rows


def write_candidate_csv(
    path: Path,
    candidates: List[SamplingCandidate],
    *,
    include_scores: bool = False,
) -> None:
    if not candidates:
        raise CalibrationError("Cannot write an empty candidate CSV")
    sample_types = {candidate.sample_type for candidate in candidates}
    if len(sample_types) != 1:
        raise CalibrationError("Candidate CSV cannot mix blur, SSIM, and ORB")
    sample_type = next(iter(sample_types))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=candidate_fieldnames(sample_type, include_scores),
        )
        writer.writeheader()
        writer.writerows(candidate_rows(candidates, include_scores))
