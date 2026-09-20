import pytest

from bankocr.domain.coordinates import Point
from bankocr.domain.text_block import SourceType, TextBlock
from bankocr.parser.grid import GridTableParser
from bankocr.parser.models import ParserOutcomeStatus
from bankocr.parser.templates import ColumnDefinition, TableTemplate


def _block(text: str, x: float, y: float, width: float = 20.0) -> TextBlock:
    return TextBlock(
        text=text,
        raw_text=text,
        polygon=(Point(x, y), Point(x + width, y), Point(x + width, y + 6), Point(x, y + 6)),
        confidence=0.95,
        source_type=SourceType.OCR,
        page_index=0,
        engine_id="test",
    )


def _template() -> TableTemplate:
    return TableTemplate(
        template_id="grid:test:v1",
        version="1",
        header_tokens=("日期", "金额"),
        columns=(ColumnDefinition("date", 0.0, 0.5), ColumnDefinition("amount", 0.5, 1.0)),
        required_fields=("date", "amount"),
    )


def test_grid_parser_uses_structure_bands_instead_of_ocr_block_rows() -> None:
    parser = GridTableParser(_template(), page_width=100.0)
    blocks = (
        _block("日期", 5, 5),
        _block("金额", 60, 5),
        _block("2026-08-01", 5, 25),
        _block("10.00", 60, 27),
        _block("2026-08-02", 5, 55),
        _block("20.00", 60, 58),
    )

    outcome = parser.parse(blocks, horizontal_boundaries=(0.0, 15.0, 45.0, 75.0))

    assert outcome.status is ParserOutcomeStatus.NEEDS_REVIEW
    assert len(outcome.candidates) == 2
    assert outcome.candidates[1].field("amount").source_block_indices == (5,)


def test_grid_parser_rejects_unsorted_structure_boundaries() -> None:
    parser = GridTableParser(_template(), page_width=100.0)

    with pytest.raises(ValueError):
        parser.parse((), horizontal_boundaries=(0.0, 20.0, 20.0))
