"""Provenance-preserving parser outputs used by review and export layers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Mapping

from bankocr.domain.text_block import SourceSpan


class CandidateStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


class ParserOutcomeStatus(str, Enum):
    SUCCESS = "success"
    NEEDS_REVIEW = "needs_review"
    PAGE_REVIEW = "page_review"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class FieldValue:
    """A field's raw OCR, secondary OCR, suggestion, and human-final value."""

    raw_text: str
    suggested_text: str | None
    final_text: str | None = None
    secondary_text: str | None = None
    confidence: float | None = None
    source_block_indices: tuple[int, ...] = ()
    source_spans: tuple[SourceSpan, ...] = ()

    def __post_init__(self) -> None:
        if not self.raw_text:
            raise ValueError("raw_text must not be empty")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if any(index < 0 for index in self.source_block_indices):
            raise ValueError("source block indexes must be non-negative")
        if any(span.page_index < 0 for span in self.source_spans):
            raise ValueError("source span page indexes must be non-negative")

    def accept(self, final_text: str | None = None) -> FieldValue:
        """Promote a suggestion or an explicit correction only when reviewed."""

        chosen = self.suggested_text if final_text is None else final_text
        return replace(self, final_text=chosen)


@dataclass(frozen=True, slots=True)
class TransactionCandidate:
    page_index: int
    row_index: int
    parser_id: str
    fields: Mapping[str, FieldValue]
    status: CandidateStatus = CandidateStatus.UNREVIEWED
    duplicate_of: tuple[int, int] | None = None
    review_order: int | None = None

    def __post_init__(self) -> None:
        if self.page_index < 0:
            raise ValueError("page_index must be non-negative")
        if self.row_index < 0:
            raise ValueError("row_index must be non-negative")
        if not self.parser_id:
            raise ValueError("parser_id must not be empty")
        if not isinstance(self.status, CandidateStatus):
            object.__setattr__(self, "status", CandidateStatus(self.status))
        if self.duplicate_of is not None:
            if len(self.duplicate_of) != 2:
                raise ValueError("duplicate_of must contain page and row indexes")
            duplicate_page, duplicate_row = self.duplicate_of
            if duplicate_page < 0 or duplicate_row < 0:
                raise ValueError("duplicate_of indexes must be non-negative")
            if (duplicate_page, duplicate_row) == (self.page_index, self.row_index):
                raise ValueError("a candidate cannot be marked as a duplicate of itself")
            if self.status is not CandidateStatus.DUPLICATE:
                raise ValueError("duplicate_of requires duplicate candidate status")
        elif self.status is CandidateStatus.DUPLICATE:
            raise ValueError("duplicate candidate status requires duplicate_of")
        if self.review_order is not None and self.review_order < 0:
            raise ValueError("review_order must be non-negative")
        items = self.fields.items() if hasattr(self.fields, "items") else self.fields
        normalized = tuple(sorted(items))
        if not normalized:
            raise ValueError("a transaction candidate must contain at least one field")
        if any(not name or not isinstance(value, FieldValue) for name, value in normalized):
            raise ValueError("fields must map non-empty names to FieldValue instances")
        object.__setattr__(self, "fields", normalized)

    def field(self, name: str) -> FieldValue:
        for field_name, value in self.fields:
            if field_name == name:
                return value
        raise KeyError(name)

    def accept(self, corrections: Mapping[str, str] | None = None) -> TransactionCandidate:
        corrections = corrections or {}
        accepted = {
            name: value.accept(corrections[name] if name in corrections else None)
            for name, value in self.fields
        }
        return replace(
            self,
            fields=accepted,
            status=CandidateStatus.ACCEPTED,
            duplicate_of=None,
        )

    def reject(self) -> TransactionCandidate:
        return replace(self, status=CandidateStatus.REJECTED, duplicate_of=None)

    def mark_duplicate(self, duplicate_of: tuple[int, int]) -> TransactionCandidate:
        return replace(
            self,
            status=CandidateStatus.DUPLICATE,
            duplicate_of=duplicate_of,
        )


@dataclass(frozen=True, slots=True)
class ParserOutcome:
    status: ParserOutcomeStatus
    candidates: tuple[TransactionCandidate, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status in (ParserOutcomeStatus.FAILED, ParserOutcomeStatus.PAGE_REVIEW):
            if self.candidates:
                raise ValueError("page-review and failed outcomes must not contain candidates")
            if not self.reason:
                raise ValueError("page-review and failed outcomes require a reason")
        elif self.reason is not None:
            raise ValueError("only failed parser outcomes may contain a reason")

    @classmethod
    def failed(cls, reason: str) -> ParserOutcome:
        return cls(ParserOutcomeStatus.FAILED, reason=reason)

    @classmethod
    def page_review(cls, reason: str) -> ParserOutcome:
        return cls(ParserOutcomeStatus.PAGE_REVIEW, reason=reason)

    @classmethod
    def success(cls, candidates: tuple[TransactionCandidate, ...]) -> ParserOutcome:
        status = (
            ParserOutcomeStatus.SUCCESS
            if all(candidate.status is CandidateStatus.ACCEPTED for candidate in candidates)
            else ParserOutcomeStatus.NEEDS_REVIEW
        )
        return cls(status=status, candidates=candidates)
