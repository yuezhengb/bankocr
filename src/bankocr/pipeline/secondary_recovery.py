"""Targeted secondary OCR driven by deterministic validation failures."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Sequence

from bankocr.domain.text_block import TextBlock
from bankocr.image.types import PageImage
from bankocr.ocr.secondary import CellRegion, SecondaryOCR
from bankocr.parser.models import FieldValue, ParserOutcome, TransactionCandidate
from bankocr.parser.normalization import normalize_amount, normalize_date, normalize_text
from bankocr.validation.engine import ValidationReport


_RECOVERABLE_CODES = {
    "invalid_amount",
    "invalid_balance",
    "invalid_date",
    "low_confidence",
    "balance_mismatch",
}


def recover_validation_fields(
    image: PageImage,
    blocks: Sequence[TextBlock],
    outcome: ParserOutcome,
    report: ValidationReport,
    secondary_ocr: SecondaryOCR,
    *,
    padding: float = 2.0,
    max_regions: int = 24,
) -> ParserOutcome:
    """Re-OCR only fields implicated by validation, preserving primary raw OCR."""

    if not outcome.candidates or not report.issues or max_regions <= 0:
        return outcome
    candidates = {
        candidate.row_index: candidate
        for candidate in outcome.candidates
    }
    targets: list[tuple[int, str]] = []
    for issue in report.issues:
        if issue.code not in _RECOVERABLE_CODES:
            continue
        candidate = candidates.get(issue.row_index)
        if candidate is None:
            continue
        for field_name in _issue_fields(candidate, issue.code, issue.field_name):
            target = (candidate.row_index, field_name)
            if target not in targets:
                targets.append(target)
            if len(targets) >= max_regions:
                break
        if len(targets) >= max_regions:
            break

    updated = dict(candidates)
    for row_index, field_name in targets:
        candidate = updated[row_index]
        field = candidate.field(field_name)
        region = _field_region(candidate.page_index, field_name, field, blocks, padding)
        if region is None:
            continue
        secondary_blocks = secondary_ocr.recognize(image, (region,))
        secondary_text = _blocks_text(secondary_blocks)
        if not secondary_text:
            continue
        suggestion = _secondary_suggestion(field_name, secondary_text)
        fields = dict(candidate.fields)
        fields[field_name] = replace(
            field,
            secondary_text=secondary_text,
            suggested_text=suggestion if suggestion is not None else field.suggested_text,
        )
        updated[row_index] = replace(candidate, fields=fields)

    return ParserOutcome.success(
        tuple(updated[candidate.row_index] for candidate in outcome.candidates)
    )


def _issue_fields(
    candidate: TransactionCandidate,
    code: str,
    field_name: str | None,
) -> tuple[str, ...]:
    fields = dict(candidate.fields)
    if field_name in fields:
        return (field_name,)
    if code == "invalid_balance":
        return tuple(name for name in ("balance", "online_balance", "closing_balance") if name in fields)
    if code == "balance_mismatch":
        return tuple(
            name
            for name in (
                "transaction_amount",
                "amount",
                "income_amount",
                "expense_amount",
                "balance",
                "online_balance",
            )
            if name in fields
        )
    return ()


def _field_region(
    page_index: int,
    field_name: str,
    field: FieldValue,
    blocks: Sequence[TextBlock],
    padding: float,
) -> CellRegion | None:
    source = [
        blocks[index]
        for index in field.source_block_indices
        if 0 <= index < len(blocks) and blocks[index].page_index == page_index
    ]
    if not source:
        return None
    return CellRegion(
        page_index=page_index,
        field_name=field_name,
        x0=min(block.bbox[0] for block in source) - padding,
        y0=min(block.bbox[1] for block in source) - padding,
        x1=max(block.bbox[2] for block in source) + padding,
        y1=max(block.bbox[3] for block in source) + padding,
    )


def _blocks_text(blocks: Sequence[TextBlock]) -> str:
    return " ".join(
        block.text.strip()
        for block in sorted(blocks, key=lambda item: (item.bbox[1], item.bbox[0]))
        if block.text.strip()
    )


def _secondary_suggestion(field_name: str, text: str) -> str | None:
    normalized_name = field_name.casefold()
    if "date" in normalized_name:
        parsed = normalize_date(text)
        return parsed.isoformat() if parsed is not None else None
    if "amount" in normalized_name or "balance" in normalized_name:
        parsed = normalize_amount(text)
        return format(parsed.quantize(Decimal("0.01")), "f") if parsed is not None else None
    normalized = normalize_text(text)
    return normalized or None
