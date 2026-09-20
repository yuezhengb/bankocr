from bankocr.domain.coordinates import Point
from bankocr.domain.text_block import SourceType, TextBlock
from bankocr.parser.models import ParserOutcomeStatus
from bankocr.parser.templates import (
    ColumnDefinition,
    TableTemplate,
    TemplateMatcher,
    WiredTableParser,
)


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


def _template(template_id: str = "bank:test:v1") -> TableTemplate:
    return TableTemplate(
        template_id=template_id,
        version="1",
        header_tokens=("日期", "金额", "余额"),
        columns=(
            ColumnDefinition("date", 0.0, 0.33),
            ColumnDefinition("amount", 0.33, 0.66),
            ColumnDefinition("balance", 0.66, 1.0),
        ),
        required_fields=("date", "amount"),
    )


def test_template_matcher_requires_enough_header_evidence() -> None:
    template = _template()
    matcher = TemplateMatcher((template,), minimum_header_score=0.66)

    match = matcher.match((_block("日期", 5, 10), _block("金额", 40, 10), _block("余额", 75, 10)))
    unknown = matcher.match((_block("收款人", 5, 10), _block("备注", 40, 10)))

    assert match is not None
    assert match.template_id == "bank:test:v1"
    assert match.matched_tokens == ("日期", "金额", "余额")
    assert unknown is None


def test_template_matcher_fails_closed_on_tied_templates() -> None:
    first = _template("bank:first:v1")
    second = _template("bank:second:v1")
    matcher = TemplateMatcher((first, second), minimum_header_score=0.5)

    assert matcher.match((_block("日期", 5, 10), _block("金额", 40, 10))) is None


def test_template_matcher_ignores_header_tokens_found_below_the_header_band() -> None:
    matcher = TemplateMatcher((_template(),), minimum_header_score=0.66)

    blocks = (
        _block("日期", 5, 700),
        _block("金额", 40, 700),
        _block("余额", 75, 700),
    )

    assert matcher.match(blocks, page_height=1000.0) is None


def test_wired_parser_skips_header_and_keeps_candidate_values_unreviewed() -> None:
    parser = WiredTableParser(_template(), page_width=100.0)
    blocks = (
        _block("日期", 5, 10),
        _block("金额", 40, 10),
        _block("余额", 75, 10),
        _block("2026-08-01", 5, 30, width=25),
        _block("10.00", 40, 30),
        _block("90.00", 75, 30),
    )

    outcome = parser.parse(blocks)

    assert outcome.status is ParserOutcomeStatus.NEEDS_REVIEW
    assert len(outcome.candidates) == 1
    candidate = outcome.candidates[0]
    assert candidate.field("date").raw_text == "2026-08-01"
    assert candidate.field("amount").suggested_text == "10.00"
    assert candidate.field("amount").final_text is None
    assert candidate.field("amount").source_block_indices == (4,)


def test_wired_parser_fails_closed_when_required_column_is_missing() -> None:
    parser = WiredTableParser(_template(), page_width=100.0)
    blocks = (
        _block("日期", 5, 10),
        _block("金额", 40, 10),
        _block("余额", 75, 10),
        _block("2026-08-01", 5, 30, width=25),
    )

    outcome = parser.parse(blocks)

    assert outcome.status is ParserOutcomeStatus.FAILED
    assert outcome.candidates == ()
    assert outcome.reason is not None
