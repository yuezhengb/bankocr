"""Visual PDF companion for checking structured OCR rows against source pages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import pymupdf

from bankocr.parser.models import CandidateStatus, TransactionCandidate
from bankocr.validation.engine import ValidationReport
from bankocr.validation.risk import ValidationRuleState

from .searchable_pdf import SearchablePdfExporter, add_searchable_text_layer
from .source_geometry import candidate_bbox, candidate_sort_key, comparison_ids


class ComparisonPdfExporter:
    """Keep source artwork and add bounded, numbered provenance markers."""

    def __init__(self, font_file: str | Path | None = None) -> None:
        self._searchable_exporter = SearchablePdfExporter(font_file=font_file)

    @property
    def font_file(self) -> Path | None:
        return self._searchable_exporter.font_file

    def export(
        self,
        source: str | Path,
        output: str | Path,
        candidates: tuple[TransactionCandidate, ...] | list[TransactionCandidate],
        blocks_by_page: Mapping[int, Sequence[object]],
        validation_reports: Mapping[int, ValidationReport] | None = None,
    ) -> Path:
        source_path = Path(source).resolve()
        output_path = Path(output).resolve()
        if source_path == output_path:
            raise ValueError("comparison PDF output must not overwrite the source PDF")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        ordered_candidates = tuple(sorted(candidates, key=candidate_sort_key))
        marker_ids = comparison_ids(ordered_candidates)
        document = pymupdf.open(str(source_path))
        try:
            add_searchable_text_layer(document, blocks_by_page, self.font_file)
            for candidate in ordered_candidates:
                bbox = candidate_bbox(candidate, blocks_by_page)
                if bbox is None:
                    continue
                page = _load_page(document, candidate.page_index)
                rect = _clip_rect(page.rect, bbox)
                if rect is None:
                    continue
                color = _marker_color(candidate, (validation_reports or {}).get(candidate.page_index))
                page.draw_rect(rect, color=color, width=1.2, overlay=True)
                _insert_marker_label(page, rect, marker_ids[(candidate.page_index, candidate.row_index)], color)
            document.save(str(output_path), garbage=3, deflate=True)
        finally:
            document.close()
        return output_path


def _load_page(document: pymupdf.Document, page_index: int) -> pymupdf.Page:
    if page_index < 0 or page_index >= document.page_count:
        raise ValueError(f"page index out of range: {page_index}")
    return document.load_page(page_index)


def _clip_rect(
    page_rect: pymupdf.Rect,
    bbox: tuple[float, float, float, float],
) -> pymupdf.Rect | None:
    x0, y0, x1, y1 = bbox
    clipped = pymupdf.Rect(
        max(page_rect.x0, x0),
        max(page_rect.y0, y0),
        min(page_rect.x1, x1),
        min(page_rect.y1, y1),
    )
    return clipped if clipped.x1 > clipped.x0 and clipped.y1 > clipped.y0 else None


def _insert_marker_label(
    page: pymupdf.Page,
    rect: pymupdf.Rect,
    label: str,
    color: tuple[float, float, float],
) -> None:
    label_height = 10.0
    label_width = max(30.0, min(48.0, len(label) * 6.0 + 4.0))
    x0 = max(page.rect.x0, min(rect.x0, page.rect.x1 - label_width))
    y1 = max(page.rect.y0 + label_height, rect.y0)
    label_rect = pymupdf.Rect(x0, y1 - label_height, x0 + label_width, y1)
    page.draw_rect(label_rect, color=color, fill=(1.0, 1.0, 1.0), width=0.5, overlay=True)
    page.insert_text(
        (label_rect.x0 + 2.0, label_rect.y1 - 2.0),
        label,
        fontsize=7.0,
        fontname="helv",
        color=color,
        overlay=True,
    )


def _marker_color(
    candidate: TransactionCandidate,
    report: ValidationReport | None,
) -> tuple[float, float, float]:
    if candidate.status in {CandidateStatus.REJECTED, CandidateStatus.DUPLICATE}:
        return (0.45, 0.45, 0.45)
    if report is not None:
        row_issues = [issue for issue in report.issues if issue.row_index == candidate.row_index]
        if any(
            issue.severity.value == "critical" and issue.rule_state is ValidationRuleState.FAIL
            for issue in row_issues
        ):
            return (0.80, 0.15, 0.10)
        if any(issue.rule_state not in {ValidationRuleState.PASS, ValidationRuleState.NOT_APPLICABLE} for issue in row_issues):
            return (0.88, 0.58, 0.05)
        if candidate.status is CandidateStatus.ACCEPTED and report.status is not None and report.status.value == "pass":
            return (0.10, 0.55, 0.20)
    return (0.88, 0.58, 0.05)
