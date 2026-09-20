"""Grid-band parser driven by structure lines, not OCR's natural text rows."""

from __future__ import annotations

from bankocr.domain.text_block import TextBlock

from .models import ParserOutcome, TransactionCandidate
from .suggestions import suggest_outcome
from .templates import TableTemplate, _fields_from_blocks, _normalize_token


class GridTableParser:
    def __init__(self, template: TableTemplate, *, page_width: float) -> None:
        if template.row_strategy != "grid":
            raise ValueError("GridTableParser requires a grid template")
        if page_width <= 0:
            raise ValueError("page_width must be positive")
        self.template = template
        self.page_width = page_width

    def parse(
        self,
        blocks: tuple[TextBlock, ...] | list[TextBlock],
        *,
        horizontal_boundaries: tuple[float, ...],
    ) -> ParserOutcome:
        if len(horizontal_boundaries) < 2:
            raise ValueError("at least two horizontal boundaries are required")
        if any(
            left >= right
            for left, right in zip(horizontal_boundaries, horizontal_boundaries[1:])
        ):
            raise ValueError("horizontal boundaries must be strictly increasing")

        source_indexes = {id(block): index for index, block in enumerate(blocks)}
        candidates: list[TransactionCandidate] = []
        for band_index, (top, bottom) in enumerate(
            zip(horizontal_boundaries, horizontal_boundaries[1:])
        ):
            row_blocks = tuple(
                block
                for block in blocks
                if top <= (block.bbox[1] + block.bbox[3]) / 2.0 < bottom
            )
            if not row_blocks or self._is_header(row_blocks):
                continue
            fields = _fields_from_blocks(self.template, row_blocks, self.page_width, source_indexes)
            if not fields:
                continue
            missing = [name for name in self.template.required_fields if name not in fields]
            if missing:
                return ParserOutcome.failed(
                    f"grid band {band_index} is missing required fields: {', '.join(missing)}"
                )
            candidates.append(
                TransactionCandidate(
                    page_index=row_blocks[0].page_index,
                    row_index=band_index,
                    parser_id=self.template.template_id,
                    fields=fields,
                )
            )
        if not candidates:
            return ParserOutcome.failed("no transaction rows found in structure grid")
        return suggest_outcome(ParserOutcome.success(tuple(candidates)))

    def _is_header(self, blocks: tuple[TextBlock, ...]) -> bool:
        text = "".join(_normalize_token(block.text) for block in blocks)
        matches = sum(_normalize_token(token) in text for token in self.template.header_tokens)
        return matches >= max(1, len(self.template.header_tokens) // 4)
