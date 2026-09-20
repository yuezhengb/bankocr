from bankocr.domain.coordinates import Point
from bankocr.domain.text_block import SourceType, TextBlock
from bankocr.parser.dispatch import GenericParser
from bankocr.parser.models import ParserOutcomeStatus
from bankocr.parser.templates import ColumnDefinition, TableTemplate


def _block(text: str, x: float, y: float, width: float = 20.0) -> TextBlock:
    return TextBlock(
        text=text,
        raw_text=text,
        polygon=(Point(x, y), Point(x + width, y), Point(x + width, y + 8), Point(x, y + 8)),
        confidence=0.99,
        source_type=SourceType.OCR,
        page_index=0,
        engine_id="test",
    )


def test_positional_parser_keeps_two_rows_with_the_same_date_separate() -> None:
    template = TableTemplate(
        template_id="positional:test:v1",
        version="1",
        header_tokens=("日期", "余额"),
        columns=(
            ColumnDefinition("transaction_date", 0.0, 0.3),
            ColumnDefinition("transaction_amount", 0.3, 0.6),
            ColumnDefinition("balance", 0.6, 1.0),
        ),
        required_fields=("transaction_date", "transaction_amount", "balance"),
        row_strategy="positional",
    )
    outcome = GenericParser((template,), page_width=100).parse(
        (
            _block("日期", 5, 10),
            _block("余额", 70, 10),
            _block("2026/08/01", 5, 50, 25),
            _block("10.00", 35, 50),
            _block("10.00", 70, 50),
            _block("2026/08/01", 5, 75, 25),
            _block("5.00", 35, 75),
            _block("15.00", 70, 75),
        )
    )
    assert outcome.status is ParserOutcomeStatus.NEEDS_REVIEW
    assert len(outcome.candidates) == 2
