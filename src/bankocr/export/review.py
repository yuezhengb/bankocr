"""Human-review Excel export with reasons and source provenance."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from bankocr.parser.models import FieldValue, TransactionCandidate
from bankocr.validation.engine import ValidationReport


class ReviewExcelExporter:
    def export(
        self,
        candidates: tuple[TransactionCandidate, ...] | list[TransactionCandidate],
        validation_reports: Mapping[int, ValidationReport],
        output: str | Path,
        *,
        source_file: str | None = None,
        page_errors: Mapping[int, str] | None = None,
    ) -> Path:
        from openpyxl import Workbook
        from openpyxl.styles import Font

        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        candidate_map = {
            (candidate.page_index, candidate.row_index): candidate
            for candidate in candidates
        }
        rows: list[tuple[object, ...]] = []
        for page_index, report in validation_reports.items():
            for issue in report.issues:
                candidate = candidate_map.get((page_index, issue.row_index))
                field = candidate.fields if candidate else ()
                value = dict(field).get(issue.field_name) if issue.field_name else None
                rows.append(
                    _row(
                        source_file,
                        page_index,
                        issue.row_index,
                        issue.code,
                        issue.severity.value,
                        issue.message,
                        candidate,
                        value,
                        issue.field_name,
                        source_page_index=issue.source_page_index,
                        source_bbox=issue.source_bbox,
                        rule_state=issue.rule_state.value,
                        validation_status=report.status.value if report.status is not None else None,
                    )
                )
        for page_index, message in (page_errors or {}).items():
            rows.append(
                _row(
                    source_file,
                    page_index,
                    -1,
                    "page_error",
                    "critical",
                    message,
                    None,
                    None,
                    None,
                    validation_status="page_review",
                )
            )
        rows.sort(key=lambda row: (int(row[1]), int(row[2]), str(row[4]), str(row[3])))

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Review Queue"
        headers = (
            "source_file",
            "page_index",
            "row_index",
            "field",
            "code",
            "severity",
            "rule_state",
            "message",
            "raw_text",
            "secondary_text",
            "suggested_text",
            "final_text",
            "confidence",
            "source_block_indices",
            "source_page_index",
            "source_bbox",
            "validation_status",
            "parser_id",
            "status",
        )
        sheet.append(headers)
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for row in rows:
            sheet.append(row)
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for column_cells in sheet.columns:
            width = min(60, max(12, max(len(str(cell.value or "")) for cell in column_cells) + 2))
            sheet.column_dimensions[column_cells[0].column_letter].width = width
        workbook.save(output_path)
        return output_path


def _row(
    source_file: str | None,
    page_index: int,
    row_index: int,
    code: str,
    severity: str,
    message: str,
    candidate: TransactionCandidate | None,
    value: FieldValue | None,
    field_name: str | None,
    *,
    source_page_index: int | None = None,
    source_bbox: tuple[float, float, float, float] | None = None,
    rule_state: str = "fail",
    validation_status: str | None = None,
) -> tuple[object, ...]:
    return (
        source_file or "",
        page_index,
        row_index,
        field_name or "",
        code,
        severity,
        rule_state,
        message,
        value.raw_text if value else None,
        value.secondary_text if value else None,
        value.suggested_text if value else None,
        value.final_text if value else None,
        value.confidence if value else None,
        ",".join(str(index) for index in value.source_block_indices) if value else None,
        source_page_index,
        None if source_bbox is None else ",".join(f"{item:g}" for item in source_bbox),
        validation_status,
        candidate.parser_id if candidate else None,
        candidate.status.value if candidate else None,
    )
