from pathlib import Path

from bankocr.domain.coordinates import Point
from bankocr.domain.text_block import SourceType, TextBlock
from bankocr.parser.models import ParserOutcomeStatus
from bankocr.parser.template_pack import TemplatePack
from bankocr.parser.templates import TemplateMatcher, WiredTableParser


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


def _load_ccb_template():
    pack_dir = Path(__file__).resolve().parents[3] / "templates" / "known"
    manifest = pack_dir.parent / "manifest.json"
    pack = TemplatePack.from_directory(pack_dir, manifest_path=manifest)
    for template in pack.templates:
        if template.template_id == "ccb_detail_v1":
            return template
    raise AssertionError("ccb_detail_v1 template not found in pack")


def test_ccb_detail_template_loads_and_verifies_structure():
    template = _load_ccb_template()

    assert template.template_id == "ccb_detail_v1"
    assert template.version == "1"
    assert template.row_strategy == "grid"
    assert template.header_tokens == (
        "记账日期",
        "交易日期",
        "交易金额",
        "账户余额",
        "对方账号",
        "对方户名",
        "交易地点/附言",
    )
    assert tuple(col.name for col in template.columns) == (
        "accounting_date",
        "transaction_date",
        "transaction_amount",
        "balance",
        "counterparty_account",
        "counterparty_name",
        "description",
    )
    assert template.required_fields == (
        "accounting_date",
        "transaction_amount",
        "balance",
    )


def test_ccb_detail_template_matches_synthetic_headers():
    template = _load_ccb_template()
    matcher = TemplateMatcher((template,), minimum_header_score=0.6)

    # 1000px wide page, headers within 22% top margin
    blocks = (
        _block("记账日期", 40, 50, width=50),
        _block("交易日期", 150, 50, width=50),
        _block("交易金额", 260, 50, width=50),
        _block("账户余额", 390, 50, width=50),
        _block("对方账号", 520, 50, width=60),
        _block("对方户名", 680, 50, width=60),
        _block("交易地点/附言", 830, 50, width=80),
    )

    match = matcher.match(blocks, page_height=1000.0)
    assert match is not None
    assert match.template_id == "ccb_detail_v1"
    assert len(match.matched_tokens) == 7


def test_ccb_detail_template_parses_synthetic_row():
    template = _load_ccb_template()
    parser = WiredTableParser(template, page_width=1000.0)

    blocks = (
        # Header tokens
        _block("记账日期", 40, 50, width=50),
        _block("交易日期", 150, 50, width=50),
        _block("交易金额", 260, 50, width=50),
        _block("账户余额", 390, 50, width=50),
        _block("对方账号", 520, 50, width=60),
        _block("对方户名", 680, 50, width=60),
        _block("交易地点/附言", 830, 50, width=80),
        # Synthetic row data
        _block("2026-03-01", 40, 120, width=70),
        _block("2026-03-01", 150, 120, width=70),
        _block("1,250.00", 260, 120, width=60),
        _block("15,800.50", 390, 120, width=70),
        _block("6217000000001234", 520, 120, width=120),
        _block("张三", 680, 120, width=40),
        _block("转账收入", 830, 120, width=60),
    )

    outcome = parser.parse(blocks)
    assert outcome.status is ParserOutcomeStatus.NEEDS_REVIEW
    assert len(outcome.candidates) == 1

    candidate = outcome.candidates[0]
    assert candidate.field("accounting_date").raw_text == "2026-03-01"
    assert candidate.field("transaction_amount").raw_text == "1,250.00"
    assert candidate.field("transaction_amount").suggested_text == "1250.00"
    assert candidate.field("balance").suggested_text == "15800.50"
    assert candidate.field("counterparty_name").raw_text == "张三"
