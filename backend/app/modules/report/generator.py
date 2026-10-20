"""
GS-Prep Backend — PDF Report Generator Module

Generates a structured PDF report using ReportLab.
Contains video information, processing metrics, and dataset summary.
"""

import logging
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
)

logger = logging.getLogger("gs_prep.modules.report")


class ReportGenerator:
    """
    Generates a PDF report summarizing the entire processing pipeline.

    Attributes:
        output_path: Path to write the PDF report.
    """

    def __init__(self, output_path: Path):
        self.output_path = output_path

    def generate(
        self,
        video_info: dict,
        extraction_info: dict,
        blur_info: dict,
        duplicate_info: dict,
        resize_info: dict,
        dataset_info: dict,
        processing_time: float,
    ) -> Path:
        """
        Generate the PDF report.

        Args:
            video_info: Video metadata dictionary.
            extraction_info: Frame extraction results.
            blur_info: Blur detection results.
            duplicate_info: Duplicate removal results.
            resize_info: Resize results.
            dataset_info: Final dataset statistics.
            processing_time: Total processing time in seconds.

        Returns:
            Path: Path to the generated PDF file.
        """
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        doc = SimpleDocTemplate(
            str(self.output_path),
            pagesize=A4,
            rightMargin=20 * mm,
            leftMargin=20 * mm,
            topMargin=20 * mm,
            bottomMargin=20 * mm,
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "CustomTitle",
            parent=styles["Title"],
            fontSize=22,
            spaceAfter=4 * mm,
            textColor=colors.HexColor("#1e1b4b"),
            alignment=0,
        )
        heading_style = ParagraphStyle(
            "CustomHeading",
            parent=styles["Heading2"],
            fontSize=13,
            spaceBefore=5 * mm,
            spaceAfter=2 * mm,
            textColor=colors.HexColor("#312e81"),
        )
        body_style = ParagraphStyle(
            "CustomBody",
            parent=styles["Normal"],
            fontSize=10,
            textColor=colors.HexColor("#4b5563"),
        )

        elements = []

        # --- Title ---
        elements.append(Paragraph("GS-Prep — Dataset Report", title_style))
        elements.append(
            Paragraph(
                f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                body_style,
            )
        )
        elements.append(Spacer(1, 4 * mm))
        elements.append(
            HRFlowable(
                width="100%", thickness=1, color=colors.HexColor("#cbd5e1")
            )
        )

        # --- Video Information ---
        elements.append(Paragraph("Video Information", heading_style))
        video_data = [
            ["Filename", str(video_info.get("filename", "N/A"))],
            ["Duration", f"{video_info.get('duration', 0):.1f} seconds"],
            ["FPS", f"{video_info.get('fps', 0):.1f}"],
            [
                "Resolution",
                f"{video_info.get('width', 0)} × {video_info.get('height', 0)}",
            ],
            ["Codec", str(video_info.get("codec", "N/A"))],
        ]
        container_info = video_info.get("container") or {}
        stream_info = video_info.get("video_stream") or {}
        audio_info = video_info.get("audio_stream") or {}
        integrity_info = video_info.get("integrity") or {}
        checksum = str(integrity_info.get("sha256") or "")
        checksum_summary = (
            f"{checksum[:16]}...{checksum[-16:]}" if len(checksum) > 35 else checksum
        )
        video_data.extend(
            [
                ["Container", str(container_info.get("format_name") or "N/A")],
                ["Bitrate", str(container_info.get("bit_rate") or "N/A")],
                ["Pixel Format", str(stream_info.get("pixel_format") or "N/A")],
                [
                    "Frame Count Source",
                    str(stream_info.get("frame_count_source") or "legacy"),
                ],
                ["Rotation", f"{stream_info.get('rotation', 0)} degrees"],
                ["Audio Codec", str(audio_info.get("codec_name") or "None")],
                [
                    "Metadata Source",
                    str(integrity_info.get("metadata_source") or "legacy"),
                ],
                ["SHA-256", checksum_summary or "N/A"],
            ]
        )
        elements.append(self._create_table(video_data))

        # --- Extraction ---
        elements.append(Paragraph("Frame Extraction", heading_style))
        extraction_data = [
            ["Extraction FPS", str(extraction_info.get("extraction_fps", 0))],
            ["Total Video Frames", str(extraction_info.get("total_frames", 0))],
            ["Extracted Frames", str(extraction_info.get("extracted_frames", 0))],
        ]
        elements.append(self._create_table(extraction_data))

        # --- Blur Detection ---
        elements.append(Paragraph("Blur Detection", heading_style))
        blur_data = [
            ["Blurry Frames Removed", str(blur_info.get("blur_removed", 0))],
            ["Remaining Frames", str(blur_info.get("remaining", 0))],
        ]
        elements.append(self._create_table(blur_data))

        # --- Duplicate Removal ---
        elements.append(Paragraph("Duplicate Removal", heading_style))
        dup_data = [
            [
                "Duplicates Removed",
                str(duplicate_info.get("duplicates_removed", 0)),
            ],
            ["Remaining Frames", str(duplicate_info.get("remaining", 0))],
        ]
        elements.append(self._create_table(dup_data))

        # --- Resize ---
        elements.append(Paragraph("Resize", heading_style))
        resize_data = [
            [
                "Final Resolution",
                f"{resize_info.get('final_width', 0)} × {resize_info.get('final_height', 0)}",
            ],
        ]
        elements.append(self._create_table(resize_data))

        # --- Dataset Summary ---
        elements.append(Paragraph("Dataset Summary", heading_style))
        extracted_frames = int(dataset_info.get("extracted_frames", 0))
        accepted_frames = int(dataset_info.get("final_images", 0))
        rejected_blur = int(dataset_info.get("rejected_blur", 0))
        rejected_duplicate = int(dataset_info.get("rejected_duplicate", 0))
        retention_rate = (
            (accepted_frames / extracted_frames) * 100 if extracted_frames else 0.0
        )
        reduction_rate = 100.0 - retention_rate if extracted_frames else 0.0
        summary_data = [
            ["Total Extracted Frames", str(extracted_frames)],
            ["Accepted Frames", str(accepted_frames)],
            ["Rejected Blur", str(rejected_blur)],
            ["Rejected Duplicate", str(rejected_duplicate)],
            ["Retention Rate", f"{retention_rate:.1f}%"],
            ["Reduction Rate", f"{reduction_rate:.1f}%"],
            ["Processing Time", f"{processing_time:.1f} seconds"],
        ]
        elements.append(self._create_table(summary_data))

        # Build
        doc.build(elements)
        logger.info("Report generated: %s", self.output_path)
        return self.output_path

    @staticmethod
    def _create_table(data: list) -> Table:
        """Create a styled two-column table with clean black text."""
        table = Table(data, colWidths=[55 * mm, 115 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8fafc")),
                    ("BACKGROUND", (1, 0), (1, -1), colors.HexColor("#ffffff")),
                    ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#334155")),
                    ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#0f172a")),
                    ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    (
                        "LINEBELOW",
                        (0, 0),
                        (-1, -1),
                        0.5,
                        colors.HexColor("#e2e8f0"),
                    ),
                    (
                        "BOX",
                        (0, 0),
                        (-1, -1),
                        0.5,
                        colors.HexColor("#cbd5e1"),
                    ),
                ]
            )
        )
        return table
