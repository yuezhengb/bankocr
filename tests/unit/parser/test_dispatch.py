from bankocr.domain.coordinates import Point
from bankocr.domain.text_block import SourceType, TextBlock
from bankocr.parser.dispatch import GenericParser
from bankocr.parser.known_templates import bohai_detail_template
from bankocr.parser.models import ParserOutcomeStatus
from bankocr.parser.templates import ColumnDefinition, TableTemplate


def _block(text: str, x: float, y: float, width: float = 20.0, height: float = 8.0) -> TextBlock:
    return TextBlock(
        text=text,
        raw_text=text,
        polygon=(
            Point(x, y),
            Point(x + width, y),
            Point(x + width, y + height),
            Point(x, y + height),
        ),
        confidence=0.95,
        source_type=SourceType.OCR,
        page_index=0,
        engine_id="test",
    )


def _anchor_template() -> TableTemplate:
    return TableTemplate(
        template_id="anchor:test:v1",
        version="1",
        header_tokens=("记账日期", "联机余额"),
        columns=(
            ColumnDefinition("accounting_date", 0.0, 0.2),
            ColumnDefinition("online_balance", 0.2, 0.5),
            ColumnDefinition("summary", 0.5, 1.0),
        ),
        required_fields=("accounting_date", "online_balance"),
        row_strategy="anchor_date",
    )


def test_generic_parser_routes_anchor_date_template_and_merges_multiline_cells() -> None:
    parser = GenericParser((_anchor_template(),), page_width=100.0)
    blocks = (
        _block("记账日期", 5, 10),
        _block("联机余额", 25, 10),
        _block("2026/08/01", 5, 100, width=15),
        _block("90.00", 25, 101),
        _block("第一行", 55, 102),
        _block("第二行", 55, 113),
        _block("2026/08/02", 5, 150, width=15),
        _block("80.00", 25, 151),
    )

    outcome = parser.parse(blocks)

    assert outcome.status is ParserOutcomeStatus.NEEDS_REVIEW
    assert len(outcome.candidates) == 2
    assert outcome.candidates[0].field("summary").raw_text == "第一行 第二行"


def test_anchor_date_parser_excludes_header_block_that_overlaps_first_row() -> None:
    parser = GenericParser((_anchor_template(),), page_width=100.0)
    blocks = (
        _block("记账日期", 5, 94, height=8),
        _block("联机余额", 25, 94, height=8),
        _block("2026/08/01", 5, 100, width=18),
        _block("90.00", 25, 101),
    )

    outcome = parser.parse(blocks)

    assert len(outcome.candidates) == 1
    assert outcome.candidates[0].field("accounting_date").raw_text == "2026/08/01"


def test_generic_parser_fails_closed_when_no_template_matches() -> None:
    parser = GenericParser((_anchor_template(),), page_width=100.0)

    outcome = parser.parse((_block("not a header", 5, 10),), page_height=100.0)

    assert outcome.status is ParserOutcomeStatus.PAGE_REVIEW
    assert outcome.candidates == ()
    assert "template" in (outcome.reason or "")


def test_generic_parser_routes_missing_critical_column_to_recoverable_page_review() -> None:
    parser = GenericParser((_anchor_template(),), page_width=100.0)
    blocks = (
        _block("璁拌处鏃ユ湡", 5, 10, width=14),
        _block("鏀跺叆閲戦", 25, 10, width=14),
        _block("2026/08/01", 5, 100, width=18),
        _block("10.00", 25, 100),
    )

    outcome = parser.parse(blocks, page_height=200.0)

    assert outcome.status is ParserOutcomeStatus.PAGE_REVIEW
    assert outcome.candidates == ()
    assert "balance" in (outcome.reason or "")


def test_generic_parser_infers_an_unknown_layout_but_keeps_it_in_review() -> None:
    parser = GenericParser((_anchor_template(),), page_width=100.0)
    blocks = (
        _block("记账日期", 5, 10, width=14),
        _block("收入金额", 25, 10, width=14),
        _block("余额", 45, 10, width=14),
        _block("摘要", 70, 10, width=14),
        _block("2026/08/01", 5, 100, width=18),
        _block("10.00", 25, 100),
        _block("90.00", 45, 100),
        _block("unknown", 70, 100, width=20),
    )

    outcome = parser.parse(blocks, page_height=200.0)

    assert outcome.status is ParserOutcomeStatus.NEEDS_REVIEW
    assert len(outcome.candidates) == 1
    assert outcome.candidates[0].parser_id.startswith("generic:")
    assert outcome.candidates[0].field("balance").raw_text == "90.00"


def test_generic_parser_marks_ambiguous_balance_columns_as_page_review() -> None:
    parser = GenericParser((_anchor_template(),), page_width=100.0)
    blocks = (
        _block("记账日期", 5, 10, width=14),
        _block("收入金额", 25, 10, width=14),
        _block("余额", 45, 10, width=12),
        _block("账户余额", 65, 10, width=16),
        _block("2026/08/01", 5, 100, width=18),
        _block("10.00", 25, 100),
        _block("90.00", 45, 100),
        _block("90.00", 65, 100),
    )

    outcome = parser.parse(blocks, page_height=200.0)

    assert outcome.status is ParserOutcomeStatus.PAGE_REVIEW
    assert outcome.candidates == ()
    assert "balance" in (outcome.reason or "")


def test_generic_parser_does_not_fallback_to_ocr_rows_for_grid_template() -> None:
    parser = GenericParser((bohai_detail_template(),), page_width=100.0)
    blocks = (
        _block("交易日期", 5, 10),
        _block("交易金额", 20, 10),
        _block("余额", 30, 10),
        _block("交易渠道", 40, 10),
        _block("摘要码描述", 50, 10),
        _block("对方账号", 60, 10),
        _block("对方名称", 70, 10),
        _block("交易时间", 90, 10),
        _block("2026-08-01", 5, 30),
        _block("10.00", 20, 30),
        _block("90.00", 30, 30),
    )

    outcome = parser.parse(blocks)

    assert outcome.status is ParserOutcomeStatus.FAILED
    assert "grid" in (outcome.reason or "")
