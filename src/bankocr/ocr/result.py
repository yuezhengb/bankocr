"""Stable OCR result types shared by all OCR engines."""

from __future__ import annotations

from dataclasses import dataclass

from bankocr.domain.text_block import TextBlock


@dataclass(frozen=True, slots=True)
class OCRPageResult:
    page_index: int
    blocks: tuple[TextBlock, ...]
    engine_id: str

    def __post_init__(self) -> None:
        if self.page_index < 0:
            raise ValueError("page_index must be non-negative")
        if not self.engine_id.strip():
            raise ValueError("engine_id must not be empty")
        mismatched = [
            block.page_index
            for block in self.blocks
            if block.page_index != self.page_index
        ]
        if mismatched:
            raise ValueError("all OCR blocks must have the result page_index")
