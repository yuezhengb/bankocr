"""Template dispatch with a fail-closed generic fallback."""

from __future__ import annotations

from bankocr.domain.text_block import TextBlock

from .anchor import AnchorDateParser
from .generic import GenericLayoutParser
from .grid import GridTableParser
from .positional import PositionalParser
from .models import ParserOutcome
from .templates import TableTemplate, TemplateMatcher


class GenericParser:
    def __init__(
        self,
        templates: tuple[TableTemplate, ...],
        *,
        page_width: float,
        minimum_header_score: float = 0.6,
    ) -> None:
        if page_width <= 0:
            raise ValueError("page_width must be positive")
        self.templates = templates
        self.page_width = page_width
        self.matcher = TemplateMatcher(templates, minimum_header_score=minimum_header_score)

    def parse(
        self,
        blocks: tuple[TextBlock, ...] | list[TextBlock],
        *,
        page_height: float | None = None,
        horizontal_boundaries: tuple[float, ...] | None = None,
    ) -> ParserOutcome:
        match = self.matcher.match(blocks, page_height=page_height)
        if match is None:
            return GenericLayoutParser(page_width=self.page_width).parse(
                blocks,
                page_height=page_height,
            )
        template = next(template for template in self.templates if template.template_id == match.template_id)
        if template.row_strategy == "anchor_date":
            return AnchorDateParser(template, page_width=self.page_width).parse(blocks)
        if template.row_strategy == "positional":
            return PositionalParser(template, page_width=self.page_width).parse(blocks)
        if template.row_strategy == "grid":
            if horizontal_boundaries is None:
                return ParserOutcome.failed(
                    "grid template requires structure-derived horizontal boundaries"
                )
            return GridTableParser(template, page_width=self.page_width).parse(
                blocks,
                horizontal_boundaries=horizontal_boundaries,
            )
        return ParserOutcome.failed(f"unsupported template row strategy: {template.row_strategy}")
