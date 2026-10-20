"""Prepare and validate all blind pilot-labeling packages in one transaction."""

import math
import random
import shutil
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from tools.calibration.io import load_manifests
from tools.calibration.models import CalibrationError, DatasetSpec
from tools.calibration_sampling.package import (
    create_labeling_package,
    validate_image_sources,
)
from tools.calibration_sampling.sampling import (
    SamplingCandidate,
    build_candidates,
    stratified_sample,
)


@dataclass(frozen=True)
class PilotConfig:
    datasets: List[DatasetSpec]
    image_roots: Dict[str, Path]
    output_dir: Path
    blur_samples: int = 60
    ssim_samples: int = 60
    orb_samples: int = 60
    bins: int = 10
    seed: int = 42
    samples_per_dataset: int | None = None
    repeat_fraction: float = 0.1
    method_dataset_ids: Dict[str, List[str]] = field(default_factory=dict)
    source_video_ids: Dict[str, str] = field(default_factory=dict)
    methods: List[str] = field(default_factory=lambda: ["blur", "ssim", "orb"])


def _repeat_candidates(
    candidates: List[SamplingCandidate], fraction: float, seed: int
) -> List[SamplingCandidate]:
    if fraction == 0:
        return []
    count = max(1, round(len(candidates) * fraction))
    count = min(count, len(candidates))
    values = list(candidates)
    rng = random.Random(seed)
    rng.shuffle(values)
    repeats = values[:count]
    rng.shuffle(repeats)
    return repeats


def _research_doc(name: str) -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "research"
        / name
    )


def _write_report(
    config: PilotConfig,
    eligible: Dict[str, List[SamplingCandidate]],
    selected: Dict[str, List[SamplingCandidate]],
    repeats: Dict[str, List[SamplingCandidate]],
    write_dir: Path | None = None,
) -> None:
    all_dataset_ids = [spec.dataset_id for spec in config.datasets]
    active_ids = {
        method: config.method_dataset_ids.get(method) or all_dataset_ids
        for method in config.methods
    }
    dataset_ids = sorted(
        {dataset_id for values in active_ids.values() for dataset_id in values}
    )
    source_video_ids = {
        config.source_video_ids.get(dataset_id, dataset_id)
        for dataset_id in dataset_ids
    }
    lines = [
        "# Pilot Labeling Package Report",
        "",
        "Status: READY FOR MANUAL LABELING",
        "",
        "This report describes package preparation only. No threshold analysis has been run.",
        "",
        "## Configuration",
        "",
        f"- Calibration dataset runs: {len(dataset_ids)}",
        f"- Dataset IDs: {', '.join(dataset_ids)}",
        f"- Unique source videos: {len(source_video_ids)}",
        f"- Source video IDs: {', '.join(sorted(source_video_ids))}",
        f"- Seed: {config.seed}",
        f"- Quantile/rank bins per dataset: {config.bins}",
        f"- Repeat fraction: {config.repeat_fraction:g}",
        "- Package mode: blind",
        "",
        "## Calibration sources",
        "",
        "| Dataset ID | Source video | Manifest | Images root | Used for |",
        "|---|---|---|---|---|",
        *[
            f"| {spec.dataset_id} | "
            f"{config.source_video_ids.get(spec.dataset_id, spec.dataset_id)} | "
            f"`{spec.manifest_path.resolve()}` | "
            f"`{config.image_roots[spec.dataset_id].resolve()}` | "
            f"{', '.join(method.upper() for method in config.methods if spec.dataset_id in active_ids[method])} |"
            for spec in config.datasets
            if spec.dataset_id in dataset_ids
        ],
        "",
        "## Composition",
        "",
        "| Method | Dataset | Eligible | Selected | Bins represented | All intended bins | Consistency repeats |",
        "|---|---|---:|---:|---|---|---:|",
    ]
    warnings: List[str] = []
    for method in config.methods:
        method_dataset_ids = active_ids[method]
        eligible_counts = Counter(item.dataset_id for item in eligible[method])
        selected_counts = Counter(item.dataset_id for item in selected[method])
        repeat_counts = Counter(item.dataset_id for item in repeats[method])
        ideal_per_dataset = math.ceil(
            len(selected[method]) / max(len(method_dataset_ids), 1)
        )
        for dataset_id in method_dataset_ids:
            strata = sorted(
                {
                    item.stratum
                    for item in selected[method]
                    if item.dataset_id == dataset_id
                }
            )
            lines.append(
                f"| {method.upper()} | {dataset_id} | "
                f"{eligible_counts[dataset_id]} | {selected_counts[dataset_id]} | "
                f"{', '.join(map(str, strata)) or '-'} | "
                f"{'YES' if len(strata) == min(config.bins, eligible_counts[dataset_id]) else 'NO'} | "
                f"{repeat_counts[dataset_id]} |"
            )
            if eligible_counts[dataset_id] == 0:
                warnings.append(
                    f"{method.upper()}: dataset {dataset_id} has no eligible candidates."
                )
            elif eligible_counts[dataset_id] < ideal_per_dataset:
                warnings.append(
                    f"{method.upper()}: dataset {dataset_id} has only "
                    f"{eligible_counts[dataset_id]} eligible candidates; below the "
                    f"approximately balanced pilot quota of {ideal_per_dataset}. "
                    "The selected distribution is reported above."
                )

    lines.extend(
        [
            "",
            "## Package locations",
            "",
            *[
                f"- {method.upper()}: `{(config.output_dir / method).resolve()}`"
                for method in config.methods
            ],
            f"- Consistency repeats: `{(config.output_dir / 'pilot_consistency').resolve()}`",
            "",
            "## Preflight validation",
            "",
            "- [x] Candidate rows originate only from the supplied calibration manifests.",
            "- [x] Candidate CSV files hide algorithm scores and production decisions.",
            "- [x] Every selected current image exists and is readable.",
            "- [x] Every duplicate `compared_with` exists and is readable.",
            "- [x] Every copied image has the same SHA-256 digest as its source.",
            "- [x] Requested methods are stored in separate packages.",
            "- [x] Candidate order is shuffled deterministically.",
            "- [x] Consistency repeats use new item IDs and must not enter threshold analysis.",
            "",
            "## Image validation",
            "",
            "- Missing current images: 0",
            "- Missing reference images: 0",
            "- Unreadable images: 0",
            "- Images modified: NO (SHA-256 verified)",
            "",
            "## Capacity notes",
            "",
        ]
    )
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- No dataset has zero eligible candidates for a requested method.")
    lines.extend(
        [
            "",
            "Stop here for manual labeling. Do not run threshold analysis until labels are complete.",
            "",
        ]
    )
    report_dir = write_dir or config.output_dir
    (report_dir / "PILOT_PACKAGE_REPORT.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def prepare_pilot_packages(
    config: PilotConfig,
) -> Dict[str, List[SamplingCandidate]]:
    if config.output_dir.exists():
        raise CalibrationError(f"Pilot output path already exists: {config.output_dir}")
    if not 0 <= config.repeat_fraction <= 1:
        raise CalibrationError("Repeat fraction must be between 0 and 1")
    if config.bins <= 0:
        raise CalibrationError("Bin count must be greater than zero")
    if not config.methods:
        raise CalibrationError("At least one pilot method is required")
    if len(config.methods) != len(set(config.methods)):
        raise CalibrationError("Pilot methods cannot contain duplicates")
    invalid_requested_methods = set(config.methods) - {"blur", "ssim", "orb"}
    if invalid_requested_methods:
        raise CalibrationError(
            f"Unknown pilot methods: {', '.join(sorted(invalid_requested_methods))}"
        )

    known_ids = {spec.dataset_id for spec in config.datasets}
    invalid_methods = set(config.method_dataset_ids) - {"blur", "ssim", "orb"}
    if invalid_methods:
        raise CalibrationError(
            f"Unknown method dataset filters: {', '.join(sorted(invalid_methods))}"
        )
    for method, dataset_ids in config.method_dataset_ids.items():
        if not dataset_ids:
            raise CalibrationError(f"Dataset filter for {method} cannot be empty")
        unknown_ids = set(dataset_ids) - known_ids
        if unknown_ids:
            raise CalibrationError(
                f"Unknown dataset IDs for {method}: {', '.join(sorted(unknown_ids))}"
            )
    active_dataset_ids = {
        dataset_id
        for method in config.methods
        for dataset_id in (config.method_dataset_ids.get(method) or known_ids)
    }
    missing_roots = active_dataset_ids - set(config.image_roots)
    if missing_roots:
        raise CalibrationError(
            f"Missing images roots for datasets: {', '.join(sorted(missing_roots))}"
        )
    unknown_roots = set(config.image_roots) - known_ids
    if unknown_roots:
        raise CalibrationError(
            f"Images root has unknown dataset IDs: {', '.join(sorted(unknown_roots))}"
        )
    unknown_source_ids = set(config.source_video_ids) - known_ids
    if unknown_source_ids:
        raise CalibrationError(
            "Source-video mapping has unknown dataset IDs: "
            f"{', '.join(sorted(unknown_source_ids))}"
        )

    research_docs = [
        _research_doc("PILOT_LABELING_CHECKLIST.md"),
        _research_doc("PILOT_RESULTS.md"),
    ]
    if "blur" in config.methods:
        research_docs.append(_research_doc("BLUR_LABELING_PROTOCOL.md"))
    if {"ssim", "orb"} & set(config.methods):
        research_docs.append(_research_doc("DUPLICATE_LABELING_PROTOCOL.md"))
    for document in research_docs:
        if not document.is_file():
            raise CalibrationError(f"Required research document is missing: {document}")

    manifests = load_manifests(config.datasets)
    requested = {
        "blur": config.blur_samples,
        "ssim": config.ssim_samples,
        "orb": config.orb_samples,
    }
    eligible: Dict[str, List[SamplingCandidate]] = {}
    selected: Dict[str, List[SamplingCandidate]] = {}
    repeats: Dict[str, List[SamplingCandidate]] = {}
    method_offsets = {"blur": 101, "ssim": 202, "orb": 303}

    # Complete all manifest and image validation before creating output.
    for method in config.methods:
        method_ids = set(config.method_dataset_ids.get(method) or known_ids)
        method_manifests = {
            key: row for key, row in manifests.items() if key[0] in method_ids
        }
        eligible[method] = build_candidates(method_manifests, method)
        selected[method] = stratified_sample(
            eligible[method],
            sample_count=requested[method],
            bins=config.bins,
            seed=config.seed,
            samples_per_dataset=config.samples_per_dataset,
        )
        validate_image_sources(selected[method], config.image_roots)
        repeats[method] = _repeat_candidates(
            selected[method],
            config.repeat_fraction,
            config.seed + method_offsets[method],
        )
        if repeats[method]:
            validate_image_sources(repeats[method], config.image_roots)

    config.output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".pilot_labeling_", dir=config.output_dir.parent
    ) as temporary_root:
        staging_output = Path(temporary_root) / "package"
        staging_output.mkdir()
        for method in config.methods:
            create_labeling_package(
                staging_output / method,
                selected[method],
                config.image_roots,
                seed=config.seed,
            )
            if repeats[method]:
                create_labeling_package(
                    staging_output / "pilot_consistency" / method,
                    repeats[method],
                    config.image_roots,
                    seed=config.seed + method_offsets[method],
                )

        for document in research_docs:
            shutil.copy2(document, staging_output / document.name)
        _write_report(config, eligible, selected, repeats, write_dir=staging_output)
        staging_output.replace(config.output_dir)
    return selected
