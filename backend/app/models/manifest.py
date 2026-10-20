"""Per-frame audit records produced while the preprocessing pipeline runs."""

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


MANIFEST_FIELDS = [
    "filename",
    "source_frame_index",
    "source_timestamp",
    "blur_score",
    "similarity_score",
    "duplicate_method",
    "compared_with",
    "status",
    "rejection_reason",
]


@dataclass(frozen=True)
class ExtractedFrameMetadata:
    """Source position associated with one extracted JPEG."""

    filename: str
    source_frame_index: int
    source_timestamp: float


@dataclass(frozen=True)
class BlurDecision:
    """Blur score and the exact decision made by BlurDetector."""

    filename: str
    blur_score: float
    is_blurry: bool


@dataclass(frozen=True)
class DuplicateDecision:
    """Similarity score and reference used by DuplicateDetector."""

    filename: str
    similarity_score: Optional[float]
    duplicate_method: str
    compared_with: Optional[str]
    is_duplicate: bool


@dataclass
class FrameManifestRecord:
    filename: str
    source_frame_index: int
    source_timestamp: float
    blur_score: Optional[float] = None
    similarity_score: Optional[float] = None
    duplicate_method: Optional[str] = None
    compared_with: Optional[str] = None
    status: str = "accepted"
    rejection_reason: Optional[str] = None

    def to_csv_row(self) -> dict:
        return {
            "filename": self.filename,
            "source_frame_index": self.source_frame_index,
            "source_timestamp": repr(self.source_timestamp),
            "blur_score": "" if self.blur_score is None else repr(self.blur_score),
            "similarity_score": (
                ""
                if self.similarity_score is None
                else repr(self.similarity_score)
            ),
            "duplicate_method": self.duplicate_method or "",
            "compared_with": self.compared_with or "",
            "status": self.status,
            "rejection_reason": self.rejection_reason or "",
        }


class FrameManifest:
    """Collect decisions as they happen and write one ordered CSV artifact."""

    def __init__(self) -> None:
        self._records: Dict[str, FrameManifestRecord] = {}

    @property
    def records(self) -> List[FrameManifestRecord]:
        return list(self._records.values())

    def record_extraction(self, metadata: ExtractedFrameMetadata) -> None:
        if metadata.filename in self._records:
            raise ValueError(f"Duplicate manifest filename: {metadata.filename}")
        self._records[metadata.filename] = FrameManifestRecord(
            filename=metadata.filename,
            source_frame_index=metadata.source_frame_index,
            source_timestamp=metadata.source_timestamp,
        )

    def record_blur(self, decision: BlurDecision) -> None:
        record = self._require_record(decision.filename)
        record.blur_score = decision.blur_score
        if decision.is_blurry:
            record.status = "rejected"
            record.rejection_reason = "blur"

    def record_duplicate(self, decision: DuplicateDecision) -> None:
        record = self._require_record(decision.filename)
        record.similarity_score = decision.similarity_score
        record.duplicate_method = decision.duplicate_method.upper()
        record.compared_with = decision.compared_with
        if decision.is_duplicate:
            record.status = "rejected"
            record.rejection_reason = "duplicate"

    def write_csv(self, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=MANIFEST_FIELDS)
            writer.writeheader()
            writer.writerows(record.to_csv_row() for record in self.records)
        return output_path

    def _require_record(self, filename: str) -> FrameManifestRecord:
        try:
            return self._records[filename]
        except KeyError as exc:
            raise ValueError(f"Missing extraction metadata for {filename}") from exc
