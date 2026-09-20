"""Shared source-location and comparison-number helpers for exports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from bankocr.parser.models import TransactionCandidate


def candidate_sort_key(candidate: TransactionCandidate) -> tuple[int, int, int]:
    return (
        candidate.page_index,
        candidate.review_order if candidate.review_order is not None else candidate.row_index,
        candidate.row_index,
    )


def comparison_ids(
    candidates: Sequence[TransactionCandidate],
) -> dict[tuple[int, int], str]:
    ordered = sorted(candidates, key=candidate_sort_key)
    return {
        (candidate.page_index, candidate.row_index): f"T{index:04d}"
        for index, candidate in enumerate(ordered, start=1)
    }


def candidate_bbox(
    candidate: TransactionCandidate,
    blocks_by_page: Mapping[int, Sequence[object]] | None,
) -> tuple[float, float, float, float] | None:
    boxes: list[tuple[float, float, float, float]] = []
    blocks = (blocks_by_page or {}).get(candidate.page_index, ())
    for _name, value in candidate.fields:
        boxes.extend(
            getattr(blocks[index], "bbox")
            for index in value.source_block_indices
            if 0 <= index < len(blocks)
        )
        boxes.extend(span.bbox for span in value.source_spans)
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def format_bbox(bbox: tuple[float, float, float, float] | None) -> str | None:
    if bbox is None:
        return None
    return ",".join(f"{value:g}" for value in bbox)
