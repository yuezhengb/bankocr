"""Audit-friendly value objects used by structured human review."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReviewOperation:
    """One user-visible structure edit in a review session.

    The indexes in this object are source row identities unless explicitly
    named ``target_position``.  Keeping that distinction prevents an audit
    record from confusing a visual move with a new OCR source row.
    """

    action: str
    page_index: int
    row_index: int | None = None
    related_page_index: int | None = None
    related_row_index: int | None = None
    target_position: int | None = None
    field_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.action.strip():
            raise ValueError("review operation action must not be empty")
        if self.page_index < 0:
            raise ValueError("review operation page_index must be non-negative")
        for name, value in (
            ("row_index", self.row_index),
            ("related_page_index", self.related_page_index),
            ("related_row_index", self.related_row_index),
            ("target_position", self.target_position),
        ):
            if value is not None and value < 0:
                raise ValueError(f"review operation {name} must be non-negative")
        if any(not name.strip() for name in self.field_names):
            raise ValueError("review operation field names must not be empty")

