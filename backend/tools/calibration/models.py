"""Typed records used by the offline calibration utility."""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


class CalibrationError(ValueError):
    """Raised when calibration inputs are invalid or ambiguous."""


@dataclass(frozen=True)
class DatasetSpec:
    dataset_id: str
    manifest_path: Path


@dataclass(frozen=True)
class ManifestRow:
    dataset_id: str
    filename: str
    blur_score: Optional[float]
    similarity_score: Optional[float]
    duplicate_method: Optional[str]
    compared_with: Optional[str]
    source_timestamp: Optional[float] = None


@dataclass(frozen=True)
class LabeledScore:
    dataset_id: str
    filename: str
    score: float
    is_positive: bool
    true_label: str
    compared_with: Optional[str] = None


@dataclass(frozen=True)
class ConfusionMatrix:
    tp: int
    fp: int
    tn: int
    fn: int

    @staticmethod
    def _divide(numerator: float, denominator: float) -> float:
        return numerator / denominator if denominator else 0.0

    @property
    def accuracy(self) -> float:
        return self._divide(self.tp + self.tn, self.tp + self.fp + self.tn + self.fn)

    @property
    def precision(self) -> float:
        return self._divide(self.tp, self.tp + self.fp)

    @property
    def recall(self) -> float:
        return self._divide(self.tp, self.tp + self.fn)

    @property
    def specificity(self) -> float:
        return self._divide(self.tn, self.tn + self.fp)

    @property
    def false_positive_rate(self) -> float:
        return self._divide(self.fp, self.fp + self.tn)

    @property
    def f1(self) -> float:
        return self._divide(2 * self.precision * self.recall, self.precision + self.recall)

    @property
    def balanced_accuracy(self) -> float:
        return (self.recall + self.specificity) / 2

    def to_dict(self) -> dict:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "tn": self.tn,
            "fn": self.fn,
            "accuracy": self.accuracy,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "specificity": self.specificity,
            "false_positive_rate": self.false_positive_rate,
            "balanced_accuracy": self.balanced_accuracy,
        }


@dataclass(frozen=True)
class ThresholdResult:
    threshold: float
    confusion: ConfusionMatrix

    def to_dict(self) -> dict:
        return {"threshold": self.threshold, **self.confusion.to_dict()}


@dataclass(frozen=True)
class AnalysisResult:
    name: str
    positive_label: str
    negative_label: str
    direction: str
    samples: List[LabeledScore]
    thresholds: List[ThresholdResult]
    selected: ThresholdResult
    recommendations: Dict[str, List[float]]
