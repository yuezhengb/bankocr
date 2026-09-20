"""Position-based parser for layouts with stable column bands but no grid lines."""

from __future__ import annotations

from bankocr.domain.text_block import TextBlock

from .anchor import AnchorDateParser
from .models import ParserOutcome
from .templates import TableTemplate


class PositionalParser:
    """Use date anchors to retain multiline cells and repeated same-date rows."""

    def __init__(self, template: TableTemplate, *, page_width: float) -> None:
        if template.row_strategy != "positional":
            raise ValueError("PositionalParser requires a positional template")
        self.template = template
        self.page_width = page_width

    def parse(self, blocks: tuple[TextBlock, ...] | list[TextBlock]) -> ParserOutcome:
        return AnchorDateParser(self.template, page_width=self.page_width).parse(blocks)
