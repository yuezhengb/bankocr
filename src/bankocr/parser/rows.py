"""Geometry-only row grouping; no bank-specific assumptions live here."""

from __future__ import annotations

from dataclasses import dataclass

from bankocr.domain.text_block import TextBlock


@dataclass(frozen=True, slots=True)
class RowGroupingOptions:
    y_tolerance: float = 8.0
    minimum_vertical_overlap: float = 0.25

    def __post_init__(self) -> None:
        if self.y_tolerance < 0:
            raise ValueError("y_tolerance must not be negative")
        if not 0.0 <= self.minimum_vertical_overlap <= 1.0:
            raise ValueError("minimum_vertical_overlap must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class RowGroup:
    blocks: tuple[TextBlock, ...]

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        boxes = tuple(block.bbox for block in self.blocks)
        return (
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        )


def group_text_blocks(
    blocks: tuple[TextBlock, ...] | list[TextBlock],
    options: RowGroupingOptions | None = None,
) -> tuple[RowGroup, ...]:
    options = options or RowGroupingOptions()
    if not blocks:
        return ()
    page_indexes = {block.page_index for block in blocks}
    if len(page_indexes) != 1:
        raise ValueError("row grouping only accepts blocks from one page")

    grouped: list[list[TextBlock]] = []
    for block in sorted(blocks, key=lambda item: (item.bbox[1], item.bbox[0])):
        best_index: int | None = None
        best_score = (-1.0, float("inf"))
        for index, row in enumerate(grouped):
            score = _row_match_score(block, row, options)
            if score is not None and score > best_score:
                best_score = score
                best_index = index
        if best_index is None:
            grouped.append([block])
        else:
            grouped[best_index].append(block)

    rows = [RowGroup(tuple(sorted(row, key=lambda item: item.bbox[0]))) for row in grouped]
    rows.sort(key=lambda row: (row.bbox[1], row.bbox[0]))
    return tuple(rows)


def _row_match_score(
    block: TextBlock,
    row: list[TextBlock],
    options: RowGroupingOptions,
) -> tuple[float, float] | None:
    block_x0, block_y0, block_x1, block_y1 = block.bbox
    row_y0 = min(item.bbox[1] for item in row)
    row_y1 = max(item.bbox[3] for item in row)
    row_center = (row_y0 + row_y1) / 2.0
    block_center = (block_y0 + block_y1) / 2.0
    overlap = max(0.0, min(block_y1, row_y1) - max(block_y0, row_y0))
    block_height = max(1e-9, block_y1 - block_y0)
    overlap_ratio = overlap / block_height
    center_distance = abs(block_center - row_center)
    if overlap_ratio < options.minimum_vertical_overlap and center_distance > options.y_tolerance:
        return None
    return overlap_ratio, -center_distance
