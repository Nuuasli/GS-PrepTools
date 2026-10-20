"""Binary classification metrics and threshold sweep logic."""

import math
from typing import Iterable, List, Optional

from tools.calibration.models import (
    AnalysisResult,
    ConfusionMatrix,
    LabeledScore,
    ThresholdResult,
)


def predict_positive(score: float, threshold: float, direction: str) -> bool:
    """Apply the production threshold direction without invoking its algorithm."""
    if direction == "below":
        return score < threshold
    if direction == "above_or_equal":
        return score >= threshold
    raise ValueError(f"Unknown threshold direction: {direction}")


def confusion_at_threshold(
    samples: Iterable[LabeledScore], threshold: float, direction: str
) -> ConfusionMatrix:
    tp = fp = tn = fn = 0
    for sample in samples:
        predicted_positive = predict_positive(sample.score, threshold, direction)
        if sample.is_positive and predicted_positive:
            tp += 1
        elif not sample.is_positive and predicted_positive:
            fp += 1
        elif not sample.is_positive and not predicted_positive:
            tn += 1
        else:
            fn += 1
    return ConfusionMatrix(tp=tp, fp=fp, tn=tn, fn=fn)


def observed_thresholds(scores: Iterable[float]) -> List[float]:
    """Use observed values plus two extrema; make no cross-method scale assumption."""
    values = sorted(set(scores))
    if not values:
        raise ValueError("Cannot generate thresholds without scores")
    scale = max(abs(values[0]), abs(values[-1]), 1.0)
    epsilon = scale * 1e-9
    return [values[0] - epsilon, *values, values[-1] + epsilon]


def ranged_thresholds(
    scores: Iterable[float],
    minimum: Optional[float],
    maximum: Optional[float],
    step: Optional[float],
) -> List[float]:
    values = list(scores)
    if not values:
        raise ValueError("Cannot generate thresholds without scores")
    if minimum is None and maximum is None and step is None:
        return observed_thresholds(values)

    start = min(values) if minimum is None else minimum
    stop = max(values) if maximum is None else maximum
    if stop < start:
        raise ValueError("Threshold maximum must be greater than or equal to minimum")
    if step is None:
        step = (stop - start) / 100 if stop > start else 1.0
    if step <= 0:
        raise ValueError("Threshold step must be greater than zero")

    count = math.floor((stop - start) / step) + 1
    if count > 100_000:
        raise ValueError("Threshold sweep would create more than 100,000 candidates")
    thresholds = [start + index * step for index in range(count)]
    if not math.isclose(thresholds[-1], stop, rel_tol=1e-12, abs_tol=1e-12):
        thresholds.append(stop)
    return thresholds


def _best_thresholds(
    results: List[ThresholdResult], metric: str, tolerance: float = 1e-12
) -> List[float]:
    best = max(getattr(result.confusion, metric) for result in results)
    return [
        result.threshold
        for result in results
        if math.isclose(
            getattr(result.confusion, metric),
            best,
            rel_tol=tolerance,
            abs_tol=tolerance,
        )
    ]


def analyze_thresholds(
    *,
    name: str,
    samples: List[LabeledScore],
    direction: str,
    positive_label: str,
    negative_label: str,
    candidates: List[float],
    target_recall: float,
) -> AnalysisResult:
    if not samples:
        raise ValueError(f"No labeled samples available for {name}")
    if not 0 <= target_recall <= 1:
        raise ValueError("Target recall must be between 0 and 1")

    results = [
        ThresholdResult(
            threshold=threshold,
            confusion=confusion_at_threshold(samples, threshold, direction),
        )
        for threshold in candidates
    ]
    highest_f1 = _best_thresholds(results, "f1")
    highest_balanced = _best_thresholds(results, "balanced_accuracy")
    recall_candidates = [
        result for result in results if result.confusion.recall >= target_recall
    ]
    recall_recommendations: List[float] = []
    if recall_candidates:
        lowest_fpr = min(
            result.confusion.false_positive_rate for result in recall_candidates
        )
        recall_recommendations = [
            result.threshold
            for result in recall_candidates
            if math.isclose(
                result.confusion.false_positive_rate,
                lowest_fpr,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        ]

    # A single threshold is needed for confusion/misclassification artifacts.
    # Tie-break: highest F1, then lowest FPR, then numerically lowest threshold.
    f1_results = [result for result in results if result.threshold in highest_f1]
    selected = sorted(
        f1_results,
        key=lambda result: (result.confusion.false_positive_rate, result.threshold),
    )[0]

    return AnalysisResult(
        name=name,
        positive_label=positive_label,
        negative_label=negative_label,
        direction=direction,
        samples=samples,
        thresholds=results,
        selected=selected,
        recommendations={
            "highest_f1": highest_f1,
            "highest_balanced_accuracy": highest_balanced,
            f"recall_at_least_{target_recall:g}_lowest_fpr": recall_recommendations,
        },
    )
