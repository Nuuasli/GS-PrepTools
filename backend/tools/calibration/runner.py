"""Orchestrate calibration loading, analysis, artifacts, and summaries."""

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from tools.calibration.io import (
    load_blur_labels,
    load_duplicate_labels,
    load_manifests,
)
from tools.calibration.metrics import (
    analyze_thresholds,
    predict_positive,
    ranged_thresholds,
)
from tools.calibration.models import (
    AnalysisResult,
    CalibrationError,
    DatasetSpec,
)
from tools.calibration.plots import create_plots


@dataclass(frozen=True)
class SweepRange:
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    step: Optional[float] = None


@dataclass(frozen=True)
class CalibrationConfig:
    datasets: List[DatasetSpec]
    output_dir: Path
    blur_label_paths: List[Path] = field(default_factory=list)
    duplicate_label_paths: List[Path] = field(default_factory=list)
    borderline_policy: str = "error"
    target_recall: float = 0.9
    generate_plots: bool = True
    blur_range: SweepRange = field(default_factory=SweepRange)
    ssim_range: SweepRange = field(default_factory=SweepRange)
    orb_range: SweepRange = field(default_factory=SweepRange)


def _write_threshold_analysis(result: AnalysisResult, output_dir: Path) -> None:
    fieldnames = [
        "threshold",
        "tp",
        "fp",
        "tn",
        "fn",
        "accuracy",
        "precision",
        "recall",
        "f1",
        "specificity",
        "false_positive_rate",
        "balanced_accuracy",
    ]
    with (output_dir / "threshold_analysis.csv").open(
        "w", newline="", encoding="utf-8"
    ) as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(item.to_dict() for item in result.thresholds)


def _write_misclassified(result: AnalysisResult, output_dir: Path) -> None:
    threshold = result.selected.threshold
    fieldnames = [
        "dataset_id",
        "filename",
        "compared_with",
        "score",
        "true_label",
        "predicted_label",
        "error_type",
        "threshold",
    ]
    rows = []
    for sample in result.samples:
        predicted_positive = predict_positive(
            sample.score, threshold, result.direction
        )
        if predicted_positive == sample.is_positive:
            continue
        rows.append(
            {
                "dataset_id": sample.dataset_id,
                "filename": sample.filename,
                "compared_with": sample.compared_with or "",
                "score": sample.score,
                "true_label": sample.true_label,
                "predicted_label": (
                    result.positive_label if predicted_positive else result.negative_label
                ),
                "error_type": "false_positive" if predicted_positive else "false_negative",
                "threshold": threshold,
            }
        )
    with (output_dir / "misclassified_frames.csv").open(
        "w", newline="", encoding="utf-8"
    ) as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_confusion_matrix(result: AnalysisResult, output_dir: Path) -> None:
    matrix = result.selected.confusion
    rows = [
        {
            "actual": result.positive_label,
            "predicted_positive": matrix.tp,
            "predicted_negative": matrix.fn,
        },
        {
            "actual": result.negative_label,
            "predicted_positive": matrix.fp,
            "predicted_negative": matrix.tn,
        },
    ]
    with (output_dir / "confusion_matrix.csv").open(
        "w", newline="", encoding="utf-8"
    ) as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=["actual", "predicted_positive", "predicted_negative"],
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_summary(
    result: AnalysisResult,
    output_dir: Path,
    dataset_ids: List[str],
    target_recall: float,
    excluded_borderline: int = 0,
) -> None:
    positives = sum(sample.is_positive for sample in result.samples)
    payload = {
        "analysis": result.name,
        "datasets": dataset_ids,
        "sample_count": len(result.samples),
        "positive_count": positives,
        "negative_count": len(result.samples) - positives,
        "positive_label": result.positive_label,
        "negative_label": result.negative_label,
        "threshold_rule": (
            "score < threshold"
            if result.direction == "below"
            else "score >= threshold"
        ),
        "observed_score_min": min(sample.score for sample in result.samples),
        "observed_score_max": max(sample.score for sample in result.samples),
        "candidate_count": len(result.thresholds),
        "target_recall": target_recall,
        "recommendations": result.recommendations,
        "diagnostic_threshold": result.selected.threshold,
        "diagnostic_threshold_tie_break": (
            "highest F1, then lowest false-positive rate, then lowest threshold"
        ),
        "diagnostic_metrics": result.selected.confusion.to_dict(),
        "excluded_borderline_count": excluded_borderline,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


def _write_analysis_artifacts(
    result: AnalysisResult,
    root_output: Path,
    dataset_ids: List[str],
    target_recall: float,
    generate_plots: bool,
    excluded_borderline: int = 0,
) -> None:
    output_dir = root_output / result.name
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_threshold_analysis(result, output_dir)
    _write_misclassified(result, output_dir)
    _write_confusion_matrix(result, output_dir)
    _write_summary(
        result,
        output_dir,
        dataset_ids,
        target_recall,
        excluded_borderline,
    )
    if generate_plots:
        create_plots(result, output_dir)


def _write_markdown_summary(
    analyses: Dict[str, AnalysisResult], output_dir: Path, target_recall: float
) -> None:
    lines = [
        "# Calibration Summary",
        "",
        "Research utility output only. Candidate thresholds are not applied to the runtime pipeline.",
        "",
        "Recommendations preserve all tied thresholds. Diagnostic artifacts use the highest-F1 candidate, then lowest false-positive rate, then lowest numeric threshold.",
        "",
    ]
    for name, result in analyses.items():
        lines.extend(
            [
                f"## {name.upper()}",
                "",
                f"- Labeled samples: {len(result.samples)}",
                f"- Diagnostic threshold: `{result.selected.threshold}`",
                f"- Diagnostic F1: `{result.selected.confusion.f1:.4f}`",
                f"- Diagnostic false-positive rate: `{result.selected.confusion.false_positive_rate:.4f}`",
                f"- Highest-F1 candidates: `{result.recommendations['highest_f1']}`",
                f"- Highest balanced-accuracy candidates: `{result.recommendations['highest_balanced_accuracy']}`",
                f"- Recall ≥ {target_recall:g}, lowest-FPR candidates: `"
                f"{result.recommendations[f'recall_at_least_{target_recall:g}_lowest_fpr']}`",
                "",
            ]
        )
    (output_dir / "calibration_summary.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def run_calibration(config: CalibrationConfig) -> Dict[str, AnalysisResult]:
    if not config.blur_label_paths and not config.duplicate_label_paths:
        raise CalibrationError(
            "Provide at least one --blur-labels or --duplicate-labels file"
        )
    if config.borderline_policy not in {"error", "exclude", "blur", "sharp"}:
        raise CalibrationError(f"Invalid borderline policy: {config.borderline_policy}")

    dataset_ids = [spec.dataset_id for spec in config.datasets]
    manifests = load_manifests(config.datasets)
    analyses: Dict[str, AnalysisResult] = {}
    excluded_borderline = 0

    if config.blur_label_paths:
        blur_samples, excluded_borderline = load_blur_labels(
            config.blur_label_paths,
            manifests,
            dataset_ids,
            config.borderline_policy,
        )
        blur_candidates = ranged_thresholds(
            (sample.score for sample in blur_samples),
            config.blur_range.minimum,
            config.blur_range.maximum,
            config.blur_range.step,
        )
        analyses["blur"] = analyze_thresholds(
            name="blur",
            samples=blur_samples,
            direction="below",
            positive_label="blur",
            negative_label="sharp",
            candidates=blur_candidates,
            target_recall=config.target_recall,
        )

    if config.duplicate_label_paths:
        duplicate_samples = load_duplicate_labels(
            config.duplicate_label_paths, manifests, dataset_ids
        )
        for method, sweep_range in (
            ("SSIM", config.ssim_range),
            ("ORB", config.orb_range),
        ):
            method_samples = duplicate_samples[method]
            if not method_samples:
                continue
            candidates = ranged_thresholds(
                (sample.score for sample in method_samples),
                sweep_range.minimum,
                sweep_range.maximum,
                sweep_range.step,
            )
            analyses[method.lower()] = analyze_thresholds(
                name=method.lower(),
                samples=method_samples,
                direction="above_or_equal",
                positive_label="duplicate",
                negative_label="keep",
                candidates=candidates,
                target_recall=config.target_recall,
            )

    config.output_dir.mkdir(parents=True, exist_ok=True)
    for name, result in analyses.items():
        _write_analysis_artifacts(
            result,
            config.output_dir,
            dataset_ids,
            config.target_recall,
            config.generate_plots,
            excluded_borderline if name == "blur" else 0,
        )
    _write_markdown_summary(analyses, config.output_dir, config.target_recall)
    return analyses
