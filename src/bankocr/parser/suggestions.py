"""Deterministic field suggestions; raw OCR and human final values remain untouched."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from .models import FieldValue, ParserOutcome, ParserOutcomeStatus, TransactionCandidate
from .normalization import normalize_amount, normalize_date, normalize_text


def suggest_candidate(candidate: TransactionCandidate) -> TransactionCandidate:
    fields: dict[str, FieldValue] = {}
    for name, value in candidate.fields:
        fields[name] = replace(value, suggested_text=_suggest_text(name, value.raw_text))
    return replace(candidate, fields=fields)


def suggest_outcome(outcome: ParserOutcome) -> ParserOutcome:
    if outcome.status is ParserOutcomeStatus.FAILED:
        return outcome
    return ParserOutcome.success(tuple(suggest_candidate(candidate) for candidate in outcome.candidates))


def _suggest_text(name: str, raw_text: str) -> str:
    normalized_name = name.casefold()
    if "date" in normalized_name:
        parsed_date = normalize_date(raw_text)
        if parsed_date is not None:
            return parsed_date.isoformat()
    if "amount" in normalized_name or "balance" in normalized_name:
        parsed_amount = normalize_amount(raw_text)
        if parsed_amount is not None:
            return format(parsed_amount.quantize(Decimal("0.01")), "f")
    return normalize_text(raw_text)
