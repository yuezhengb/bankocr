"""Pure review state used by both tests and the optional desktop UI."""

from __future__ import annotations

from dataclasses import dataclass, replace

from bankocr.domain.review import ReviewOperation
from bankocr.parser.models import FieldValue
from bankocr.parser.models import CandidateStatus, TransactionCandidate


@dataclass(frozen=True, slots=True)
class ReviewSession:
    candidates: tuple[TransactionCandidate, ...]
    edits: tuple[tuple[int, str, str], ...] = ()
    operations: tuple[ReviewOperation, ...] = ()

    @property
    def pending_count(self) -> int:
        return sum(candidate.status is CandidateStatus.UNREVIEWED for candidate in self.candidates)

    def edit_field(self, row_index: int, field_name: str, value: str) -> ReviewSession:
        candidate = self._candidate(row_index)
        candidate.field(field_name)
        if not value:
            raise ValueError("review value must not be empty")
        edits = tuple(
            edit
            for edit in self.edits
            if not (edit[0] == row_index and edit[1] == field_name)
        )
        return replace(self, edits=edits + ((row_index, field_name, value),))

    def accept(self, row_index: int) -> ReviewSession:
        candidate = self._candidate(row_index)
        corrections = {
            field_name: value
            for candidate_index, field_name, value in self.edits
            if candidate_index == row_index
        }
        accepted = candidate.accept(corrections)
        candidates = self.candidates[:row_index] + (accepted,) + self.candidates[row_index + 1 :]
        return replace(self, candidates=candidates, edits=self._without_candidate_edits(row_index))

    def reject(self, row_index: int) -> ReviewSession:
        candidate = self._candidate(row_index)
        rejected = candidate.reject()
        candidates = self.candidates[:row_index] + (rejected,) + self.candidates[row_index + 1 :]
        return replace(self, candidates=candidates, edits=self._without_candidate_edits(row_index))

    def move_candidate(self, row_index: int, target_position: int) -> ReviewSession:
        candidate = self._candidate(row_index)
        target = self._candidate(target_position)
        if candidate.page_index != target.page_index:
            raise ValueError("a candidate can only move within its source page")
        reordered = list(self.candidates)
        item = reordered.pop(row_index)
        reordered.insert(target_position, item)
        candidates = self._with_review_order(tuple(reordered))
        operation = ReviewOperation(
            action="move",
            page_index=candidate.page_index,
            row_index=candidate.row_index,
            target_position=target_position,
        )
        return replace(self, candidates=candidates, operations=self.operations + (operation,))

    def merge_candidates(self, first_index: int, second_index: int) -> ReviewSession:
        first = self._candidate(first_index)
        second = self._candidate(second_index)
        if first_index == second_index:
            raise ValueError("cannot merge a candidate with itself")
        if first.page_index != second.page_index:
            raise ValueError("candidates can only be merged within one source page")
        merged = TransactionCandidate(
            page_index=first.page_index,
            row_index=first.row_index,
            parser_id=f"review:merge:{first.parser_id}",
            fields=_merge_fields(first, second),
            status=CandidateStatus.UNREVIEWED,
            review_order=min(
                value
                for value in (first.review_order, second.review_order)
                if value is not None
            )
            if first.review_order is not None or second.review_order is not None
            else None,
        )
        remaining = [
            candidate
            for index, candidate in enumerate(self.candidates)
            if index not in {first_index, second_index}
        ]
        insert_at = min(first_index, second_index)
        remaining.insert(insert_at, merged)
        candidates = self._with_review_order(tuple(remaining))
        operation = ReviewOperation(
            action="merge",
            page_index=first.page_index,
            row_index=first.row_index,
            related_page_index=second.page_index,
            related_row_index=second.row_index,
        )
        return replace(self, candidates=candidates, operations=self.operations + (operation,))

    def split_candidate(
        self,
        row_index: int,
        field_names: tuple[str, ...] | list[str],
    ) -> ReviewSession:
        candidate = self._candidate(row_index)
        selected_names = tuple(dict.fromkeys(field_names))
        if not selected_names:
            raise ValueError("split requires at least one field")
        fields = dict(candidate.fields)
        missing = [name for name in selected_names if name not in fields]
        if missing:
            raise KeyError(missing[0])
        if len(selected_names) == len(fields):
            raise ValueError("split must leave at least one field in the original row")
        original = TransactionCandidate(
            page_index=candidate.page_index,
            row_index=candidate.row_index,
            parser_id=candidate.parser_id,
            fields={name: value for name, value in fields.items() if name not in selected_names},
            status=CandidateStatus.UNREVIEWED,
        )
        next_row = max(
            (item.row_index for item in self.candidates if item.page_index == candidate.page_index),
            default=-1,
        ) + 1
        created = TransactionCandidate(
            page_index=candidate.page_index,
            row_index=next_row,
            parser_id=f"review:split:{candidate.parser_id}",
            fields={name: fields[name] for name in selected_names},
            status=CandidateStatus.UNREVIEWED,
        )
        reordered = list(self.candidates)
        reordered[row_index : row_index + 1] = [original, created]
        candidates = self._with_review_order(tuple(reordered))
        operation = ReviewOperation(
            action="split",
            page_index=candidate.page_index,
            row_index=candidate.row_index,
            related_page_index=candidate.page_index,
            related_row_index=created.row_index,
            field_names=selected_names,
        )
        return replace(self, candidates=candidates, operations=self.operations + (operation,))

    def add_candidate(
        self,
        candidate: TransactionCandidate,
        position: int | None = None,
    ) -> ReviewSession:
        if position is None:
            position = len(self.candidates)
        if position < 0 or position > len(self.candidates):
            raise IndexError(position)
        existing_ids = {
            (item.page_index, item.row_index)
            for item in self.candidates
        }
        added = candidate
        if (added.page_index, added.row_index) in existing_ids:
            next_row = max(
                (item.row_index for item in self.candidates if item.page_index == added.page_index),
                default=-1,
            ) + 1
            added = replace(added, row_index=next_row)
        reordered = list(self.candidates)
        reordered.insert(position, added)
        candidates = self._with_review_order(tuple(reordered))
        operation = ReviewOperation(
            action="add",
            page_index=added.page_index,
            row_index=added.row_index,
            target_position=position,
        )
        return replace(self, candidates=candidates, operations=self.operations + (operation,))

    def mark_duplicate(self, row_index: int, duplicate_of_index: int) -> ReviewSession:
        candidate = self._candidate(row_index)
        target = self._candidate(duplicate_of_index)
        if row_index == duplicate_of_index:
            raise ValueError("a candidate cannot be marked as a duplicate of itself")
        duplicate = candidate.mark_duplicate((target.page_index, target.row_index))
        candidates = self.candidates[:row_index] + (duplicate,) + self.candidates[row_index + 1 :]
        operation = ReviewOperation(
            action="mark_duplicate",
            page_index=candidate.page_index,
            row_index=candidate.row_index,
            related_page_index=target.page_index,
            related_row_index=target.row_index,
        )
        return replace(self, candidates=candidates, operations=self.operations + (operation,))

    def _without_candidate_edits(self, row_index: int) -> tuple[tuple[int, str, str], ...]:
        return tuple(edit for edit in self.edits if edit[0] != row_index)

    def _candidate(self, row_index: int) -> TransactionCandidate:
        if row_index < 0 or row_index >= len(self.candidates):
            raise IndexError(row_index)
        return self.candidates[row_index]

    @staticmethod
    def _with_review_order(candidates: tuple[TransactionCandidate, ...]) -> tuple[TransactionCandidate, ...]:
        next_order: dict[int, int] = {}
        normalized: list[TransactionCandidate] = []
        for candidate in candidates:
            order = next_order.setdefault(candidate.page_index, 0)
            normalized.append(replace(candidate, review_order=order))
            next_order[candidate.page_index] = order + 1
        return tuple(normalized)


def _merge_fields(
    first: TransactionCandidate,
    second: TransactionCandidate,
) -> dict[str, FieldValue]:
    first_fields = dict(first.fields)
    second_fields = dict(second.fields)
    merged: dict[str, FieldValue] = {}
    for name in sorted(set(first_fields) | set(second_fields)):
        left = first_fields.get(name)
        right = second_fields.get(name)
        if left is None:
            merged[name] = replace(right, final_text=None)  # type: ignore[arg-type]
            continue
        if right is None:
            merged[name] = replace(left, final_text=None)
            continue
        merged[name] = FieldValue(
            raw_text=f"{left.raw_text} | {right.raw_text}",
            suggested_text=_join_optional(left.suggested_text, right.suggested_text),
            final_text=None,
            secondary_text=_join_optional(left.secondary_text, right.secondary_text),
            confidence=_minimum_confidence(left.confidence, right.confidence),
            source_block_indices=tuple(dict.fromkeys(left.source_block_indices + right.source_block_indices)),
            source_spans=tuple(dict.fromkeys(left.source_spans + right.source_spans)),
        )
    return merged


def _join_optional(left: str | None, right: str | None) -> str | None:
    values = tuple(value for value in (left, right) if value)
    return " | ".join(values) if values else None


def _minimum_confidence(left: float | None, right: float | None) -> float | None:
    values = tuple(value for value in (left, right) if value is not None)
    return min(values) if values else None
