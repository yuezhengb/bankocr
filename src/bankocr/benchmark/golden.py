"""Load field-level Golden Sample annotations without exposing source documents."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .fields import GoldenTransactionTruth


@dataclass(frozen=True, slots=True)
class GoldenSample:
    sample_id: str
    truths: tuple[GoldenTransactionTruth, ...]


def load_golden_sample(path: str | Path) -> GoldenSample:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid Golden Sample JSON: {source}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Golden Sample root must be an object")

    sample_id = payload.get("sample_id")
    if not isinstance(sample_id, str) or not sample_id.strip():
        raise ValueError("sample_id must be a non-empty string")
    records = payload.get("transactions")
    if not isinstance(records, list):
        raise ValueError("transactions must be a list")

    truths: list[GoldenTransactionTruth] = []
    seen: set[tuple[int, int]] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"transaction {index} must be an object")
        page_index = _non_negative_int(record.get("page_index"), f"transaction {index} page_index")
        row_index = _non_negative_int(record.get("row_index"), f"transaction {index} row_index")
        key = (page_index, row_index)
        if key in seen:
            raise ValueError(f"duplicate truth key: {key}")
        seen.add(key)
        fields = record.get("fields")
        if not isinstance(fields, dict):
            raise ValueError(f"transaction {index} fields must be an object")
        if not all(isinstance(name, str) for name in fields):
            raise ValueError("field names must be strings")
        if not all(isinstance(value, str) for value in fields.values()):
            raise ValueError("field values must be strings")
        truths.append(
            GoldenTransactionTruth(
                page_index=page_index,
                row_index=row_index,
                fields=dict(fields),
            )
        )
    return GoldenSample(sample_id=sample_id.strip(), truths=tuple(truths))


def _non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value
