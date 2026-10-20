"""Accurate, auditable metadata extraction for uploaded video files."""

import json
import logging
import math
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, Optional

import cv2

from app.core.config import settings
from app.models.schemas import (
    AudioStreamMetadata,
    ContainerMetadata,
    MediaIntegrityMetadata,
    VideoMetadata,
    VideoStreamMetadata,
)

logger = logging.getLogger("gs_prep.services.video_metadata")


class MetadataExtractionError(ValueError):
    """Raised when an uploaded file has no usable video stream."""


@dataclass(frozen=True)
class OpenCVProbe:
    fps: float
    total_frames: int
    width: int
    height: int
    codec: str

    @property
    def duration(self) -> float:
        return self.total_frames / self.fps if self.fps > 0 else 0.0


def _finite_float(value: Any) -> Optional[float]:
    if value in (None, "", "N/A"):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _positive_int(value: Any) -> Optional[int]:
    parsed = _finite_float(value)
    if parsed is None or parsed <= 0:
        return None
    return int(parsed)


def _nonnegative_int(value: Any) -> Optional[int]:
    parsed = _finite_float(value)
    if parsed is None or parsed < 0:
        return None
    return int(parsed)


def _frame_rate(value: Any) -> Optional[float]:
    if value in (None, "", "N/A", "0/0"):
        return None
    try:
        if isinstance(value, str) and "/" in value:
            parsed = float(Fraction(value))
        else:
            parsed = float(value)
    except (ValueError, ZeroDivisionError, TypeError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def _clean_string(value: Any) -> Optional[str]:
    if value in (None, "", "N/A", "unknown"):
        return None
    return str(value).strip() or None


def _rotation(stream: Dict[str, Any]) -> int:
    raw_rotation = (stream.get("tags") or {}).get("rotate")
    if raw_rotation is None:
        for side_data in stream.get("side_data_list") or []:
            if side_data.get("rotation") is not None:
                raw_rotation = side_data["rotation"]
                break
    parsed = _finite_float(raw_rotation)
    if parsed is None:
        return 0
    return int(round(parsed)) % 360


def _possible_vfr(average_rate: Optional[float], real_rate: Optional[float]) -> bool:
    if average_rate is None or real_rate is None:
        return False
    tolerance = max(0.01, average_rate * 0.001)
    return abs(average_rate - real_rate) > tolerance


class VideoMetadataExtractor:
    """Use FFprobe as primary source and OpenCV only for cross-check/fallback."""

    def __init__(self, ffprobe_binary: str, timeout_seconds: int):
        self.ffprobe_binary = ffprobe_binary
        self.timeout_seconds = timeout_seconds

    def _run_ffprobe_json(
        self, command: list[str], *, operation: str
    ) -> Dict[str, Any]:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise MetadataExtractionError(
                f"FFprobe executable was not found: {self.ffprobe_binary}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise MetadataExtractionError(
                f"FFprobe {operation} timed out after {self.timeout_seconds} seconds"
            ) from exc

        if result.returncode != 0:
            detail = (result.stderr or "unknown FFprobe error").strip()[:300]
            raise MetadataExtractionError(f"FFprobe {operation} failed: {detail}")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise MetadataExtractionError(
                f"FFprobe {operation} returned invalid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise MetadataExtractionError(
                f"FFprobe {operation} returned an invalid payload"
            )
        return payload

    def _run_ffprobe(self, path: Path) -> Dict[str, Any]:
        """Read stream/container headers without decoding the entire video."""
        command = [
            self.ffprobe_binary,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ]
        return self._run_ffprobe_json(command, operation="metadata probe")

    def _run_ffprobe_frame_count(self, path: Path) -> Optional[int]:
        """Count decoded video frames only when the stream header has no count."""
        command = [
            self.ffprobe_binary,
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "json",
            str(path),
        ]
        payload = self._run_ffprobe_json(command, operation="frame count")
        streams = payload.get("streams") or []
        if not streams:
            return None
        return _positive_int(streams[0].get("nb_read_frames"))

    @staticmethod
    def _opencv_probe(path: Path) -> OpenCVProbe:
        capture = cv2.VideoCapture(str(path))
        try:
            if not capture.isOpened():
                raise MetadataExtractionError("OpenCV cannot open the video stream")
            fps = float(capture.get(cv2.CAP_PROP_FPS))
            total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fourcc = int(capture.get(cv2.CAP_PROP_FOURCC))
            codec = "".join(
                chr((fourcc >> shift) & 0xFF) for shift in (0, 8, 16, 24)
            ).strip("\x00 ")
            if width <= 0 or height <= 0:
                raise MetadataExtractionError("Video has an invalid resolution")
            return OpenCVProbe(
                fps=fps if math.isfinite(fps) and fps > 0 else 0.0,
                total_frames=max(total_frames, 0),
                width=width,
                height=height,
                codec=codec,
            )
        finally:
            capture.release()

    @staticmethod
    def _cross_check(
        summary: Dict[str, Any], probe: OpenCVProbe, warnings: list[str]
    ) -> bool:
        used_fallback = False
        for field_name in ("width", "height"):
            ffprobe_value = int(summary[field_name] or 0)
            opencv_value = int(getattr(probe, field_name))
            if ffprobe_value <= 0:
                summary[field_name] = opencv_value
                used_fallback = True
            elif ffprobe_value != opencv_value:
                warnings.append(
                    f"FFprobe/OpenCV {field_name} mismatch: "
                    f"{ffprobe_value} vs {opencv_value}; FFprobe retained"
                )

        if summary["fps"] <= 0 and probe.fps > 0:
            summary["fps"] = probe.fps
            used_fallback = True
        elif probe.fps > 0 and abs(summary["fps"] - probe.fps) > 0.05:
            warnings.append(
                f"FFprobe/OpenCV FPS mismatch: {summary['fps']:.6g} vs "
                f"{probe.fps:.6g}; FFprobe retained"
            )

        if summary["total_frames"] <= 0 and probe.total_frames > 0:
            summary["total_frames"] = probe.total_frames
            summary["frame_count_source"] = "opencv_header"
            used_fallback = True
        elif probe.total_frames > 0:
            tolerance = max(1, round(summary["total_frames"] * 0.01))
            if abs(summary["total_frames"] - probe.total_frames) > tolerance:
                warnings.append(
                    "FFprobe/OpenCV frame-count mismatch: "
                    f"{summary['total_frames']} vs {probe.total_frames}; "
                    "FFprobe retained"
                )

        if summary["duration"] <= 0 and probe.duration > 0:
            summary["duration"] = probe.duration
            summary["duration_source"] = "opencv_frame_count_div_fps"
            used_fallback = True
        if not summary["codec"] and probe.codec:
            summary["codec"] = probe.codec
            used_fallback = True
        return used_fallback

    def extract(
        self,
        path: Path,
        *,
        original_filename: str,
        file_size: int,
        sha256: str,
    ) -> VideoMetadata:
        warnings: list[str] = []
        try:
            payload = self._run_ffprobe(path)
        except MetadataExtractionError as ffprobe_error:
            logger.warning("%s; falling back to OpenCV", ffprobe_error)
            warnings.append(str(ffprobe_error))
            probe = self._opencv_probe(path)
            return VideoMetadata(
                filename=original_filename,
                duration=probe.duration,
                fps=probe.fps,
                total_frames=probe.total_frames,
                width=probe.width,
                height=probe.height,
                codec=probe.codec or "unknown",
                file_size=file_size,
                video_stream=VideoStreamMetadata(
                    codec_name=probe.codec or None,
                    average_frame_rate=probe.fps or None,
                    frame_count_source="opencv_header",
                    duration_source="opencv_frame_count_div_fps",
                    coded_width=probe.width,
                    coded_height=probe.height,
                ),
                integrity=MediaIntegrityMetadata(
                    sha256=sha256,
                    metadata_source="opencv_fallback",
                    warnings=warnings,
                ),
            )

        streams = payload.get("streams") or []
        video_stream = next(
            (stream for stream in streams if stream.get("codec_type") == "video"),
            None,
        )
        if not video_stream:
            raise MetadataExtractionError("FFprobe found no video stream")
        audio_stream = next(
            (stream for stream in streams if stream.get("codec_type") == "audio"),
            None,
        )
        format_data = payload.get("format") or {}

        average_rate = _frame_rate(video_stream.get("avg_frame_rate"))
        real_rate = _frame_rate(video_stream.get("r_frame_rate"))
        fps = average_rate or real_rate or 0.0
        possible_vfr = _possible_vfr(average_rate, real_rate)
        if possible_vfr:
            warnings.append(
                "Average and real frame rates differ; the source may use variable frame rate"
            )

        duration = _finite_float(format_data.get("duration"))
        duration_source = "container"
        if duration is None or duration <= 0:
            duration = _finite_float(video_stream.get("duration"))
            duration_source = "video_stream"
        if duration is None or duration <= 0:
            duration = 0.0
            duration_source = "unknown"

        total_frames = _positive_int(video_stream.get("nb_frames"))
        frame_count_source = "ffprobe_stream_header"
        if total_frames is None:
            try:
                total_frames = self._run_ffprobe_frame_count(path)
            except MetadataExtractionError as exc:
                warnings.append(f"Exact frame count unavailable: {exc}")
            else:
                if total_frames is not None:
                    frame_count_source = "ffprobe_count_frames"
                else:
                    warnings.append(
                        "Exact frame count was not reported by FFprobe frame count"
                    )
        if total_frames is None and duration > 0 and fps > 0:
            total_frames = round(duration * fps)
            frame_count_source = "duration_times_average_fps_estimate"
            warnings.append("Exact frame count was unavailable; value was estimated")
        if total_frames is None:
            total_frames = 0
            frame_count_source = "unknown"
            warnings.append("Frame count is unavailable")

        summary: Dict[str, Any] = {
            "duration": duration,
            "duration_source": duration_source,
            "fps": fps,
            "total_frames": total_frames,
            "frame_count_source": frame_count_source,
            "width": _positive_int(video_stream.get("width")) or 0,
            "height": _positive_int(video_stream.get("height")) or 0,
            "codec": _clean_string(video_stream.get("codec_name")) or "",
        }

        metadata_source = "ffprobe"
        try:
            opencv_probe = self._opencv_probe(path)
        except MetadataExtractionError as exc:
            warnings.append(f"OpenCV cross-check unavailable: {exc}")
        else:
            if self._cross_check(summary, opencv_probe, warnings):
                metadata_source = "ffprobe+opencv_fallback"

        if summary["width"] <= 0 or summary["height"] <= 0:
            raise MetadataExtractionError("Video stream has an invalid resolution")
        if summary["fps"] <= 0:
            warnings.append("Frame rate is unavailable or invalid")
        if summary["duration"] <= 0:
            warnings.append("Duration is unavailable or invalid")

        bit_depth = _positive_int(video_stream.get("bits_per_raw_sample"))
        video_details = VideoStreamMetadata(
            stream_index=_nonnegative_int(video_stream.get("index")),
            codec_name=_clean_string(video_stream.get("codec_name"))
            or summary["codec"],
            codec_long_name=_clean_string(video_stream.get("codec_long_name")),
            profile=_clean_string(video_stream.get("profile")),
            level=_positive_int(video_stream.get("level")),
            pixel_format=_clean_string(video_stream.get("pix_fmt")),
            bit_depth=bit_depth,
            coded_width=_positive_int(video_stream.get("coded_width"))
            or summary["width"],
            coded_height=_positive_int(video_stream.get("coded_height"))
            or summary["height"],
            average_frame_rate=average_rate or summary["fps"] or None,
            nominal_frame_rate=real_rate,
            frame_count_source=summary["frame_count_source"],
            duration_source=summary["duration_source"],
            possible_variable_frame_rate=possible_vfr,
            sample_aspect_ratio=_clean_string(video_stream.get("sample_aspect_ratio")),
            display_aspect_ratio=_clean_string(video_stream.get("display_aspect_ratio")),
            rotation=_rotation(video_stream),
            bit_rate=_positive_int(video_stream.get("bit_rate")),
            time_base=_clean_string(video_stream.get("time_base")),
            color_range=_clean_string(video_stream.get("color_range")),
            color_space=_clean_string(video_stream.get("color_space")),
            color_transfer=_clean_string(video_stream.get("color_transfer")),
            color_primaries=_clean_string(video_stream.get("color_primaries")),
            field_order=_clean_string(video_stream.get("field_order")),
        )

        audio_details = None
        if audio_stream:
            audio_details = AudioStreamMetadata(
                stream_index=_nonnegative_int(audio_stream.get("index")),
                codec_name=_clean_string(audio_stream.get("codec_name")),
                codec_long_name=_clean_string(audio_stream.get("codec_long_name")),
                profile=_clean_string(audio_stream.get("profile")),
                sample_rate=_positive_int(audio_stream.get("sample_rate")),
                channels=_positive_int(audio_stream.get("channels")),
                channel_layout=_clean_string(audio_stream.get("channel_layout")),
                bit_rate=_positive_int(audio_stream.get("bit_rate")),
            )

        container = ContainerMetadata(
            format_name=_clean_string(format_data.get("format_name")),
            format_long_name=_clean_string(format_data.get("format_long_name")),
            duration=_finite_float(format_data.get("duration")),
            start_time=_finite_float(format_data.get("start_time")),
            bit_rate=_positive_int(format_data.get("bit_rate")),
            stream_count=_positive_int(format_data.get("nb_streams"))
            or len(streams),
        )

        return VideoMetadata(
            filename=original_filename,
            duration=float(summary["duration"]),
            fps=float(summary["fps"]),
            total_frames=int(summary["total_frames"]),
            width=int(summary["width"]),
            height=int(summary["height"]),
            codec=summary["codec"] or "unknown",
            file_size=file_size,
            container=container,
            video_stream=video_details,
            audio_stream=audio_details,
            integrity=MediaIntegrityMetadata(
                sha256=sha256,
                metadata_source=metadata_source,
                warnings=warnings,
            ),
        )


video_metadata_extractor = VideoMetadataExtractor(
    ffprobe_binary=settings.ffprobe_binary,
    timeout_seconds=settings.ffprobe_timeout_seconds,
)
