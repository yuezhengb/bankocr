"""Date-anchor parsing for statement layouts without reliable inner grid lines."""

from __future__ import annotations

from dataclasses import dataclass

from bankocr.domain.text_block import TextBlock

from .models import ParserOutcome, TransactionCandidate
from .normalization import normalize_date
from .suggestions import suggest_outcome
from .templates import TableTemplate, _fields_from_blocks


@dataclass(frozen=True, slots=True)
class AnchorParserOptions:
    anchor_padding: float = 5.0
    separator_padding: float = 5.0

    def __post_init__(self) -> None:
        if self.anchor_padding < 0 or self.separator_padding < 0:
            raise ValueError("anchor padding values must not be negative")


class AnchorDateParser:
    def __init__(
        self,
        template: TableTemplate,
        *,
        page_width: float,
        options: AnchorParserOptions | None = None,
    ) -> None:
        if template.row_strategy not in ("anchor_date", "positional"):
            raise ValueError("AnchorDateParser requires an anchor_date or positional template")
        if page_width <= 0:
            raise ValueError("page_width must be positive")
        self.template = template
        self.page_width = page_width
        self.options = options or AnchorParserOptions()

    def parse(self, blocks: tuple[TextBlock, ...] | list[TextBlock]) -> ParserOutcome:
        source_indexes = {id(block): index for index, block in enumerate(blocks)}
        anchors = sorted(
            (
                block
                for block in blocks
                if self._is_date_anchor(block)
            ),
            key=lambda block: (block.bbox[1], block.bbox[0]),
        )
        if not anchors:
            return ParserOutcome.failed("no date anchors found for anchor_date template")

        page_bottom = max(block.bbox[3] for block in blocks)
        candidates: list[TransactionCandidate] = []
        for row_index, anchor in enumerate(anchors):
            # Never pull the header band into the first row.  The old
            # padding-based lower bound made a header block whose baseline was
            # close to the first date look like transaction data.  Multiline
            # cells below the anchor remain included by the upper boundary.
            top = anchor.bbox[1]
            next_top = (
                anchors[row_index + 1].bbox[1] - self.options.separator_padding
                if row_index + 1 < len(anchors)
                else page_bottom + 1.0
            )
            row_blocks = tuple(
                block
                for block in blocks
                if top <= (block.bbox[1] + block.bbox[3]) / 2.0 < next_top
            )
            fields = _fields_from_blocks(self.template, row_blocks, self.page_width, source_indexes)
            missing = [name for name in self.template.required_fields if name not in fields]
            if missing:
                return ParserOutcome.failed(
                    f"anchor row {row_index} is missing required fields: {', '.join(missing)}"
                )
            candidates.append(
                TransactionCandidate(
                    page_index=anchor.page_index,
                    row_index=row_index,
                    parser_id=self.template.template_id,
                    fields=fields,
                )
            )
        return suggest_outcome(ParserOutcome.success(tuple(candidates)))

    def _is_date_anchor(self, block: TextBlock) -> bool:
        column = next(
            (
                item
                for item in self.template.columns
                if item.name in {"accounting_date", "transaction_date", "date"}
            ),
            None,
        )
        if column is None:
            raise ValueError("date-anchor template must declare a date column")
        center_x = (block.bbox[0] + block.bbox[2]) / 2.0
        return column.contains(center_x / self.page_width) and normalize_date(block.text) is not None
