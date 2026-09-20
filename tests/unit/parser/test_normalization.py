from datetime import date
from decimal import Decimal

import pytest

from bankocr.parser.normalization import normalize_amount, normalize_date, normalize_text


def test_normalize_text_uses_unicode_compatibility_and_preserves_value_meaning() -> None:
    assert normalize_text("  ＣＮＹ　 10.00\n") == "CNY 10.00"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,234.50", Decimal("1234.50")),
        ("299,00", Decimal("299.00")),
        ("10,000", Decimal("10000")),
        ("￥ 20.00", Decimal("20.00")),
        ("(20.00)", Decimal("-20.00")),
        ("-0.50", Decimal("-0.50")),
    ],
)
def test_normalize_amount_accepts_only_deterministic_money_forms(raw: str, expected: Decimal) -> None:
    assert normalize_amount(raw) == expected


@pytest.mark.parametrize("raw", ["1O.00", "12.3.4", "", "N/A", "1.234"])
def test_normalize_amount_rejects_ambiguous_or_unsupported_forms(raw: str) -> None:
    assert normalize_amount(raw) is None


def test_normalize_amount_preserves_decimal_comma_only_when_unambiguous() -> None:
    assert normalize_amount("10,00") == Decimal("10.00")
    assert normalize_amount("10,000.00") == Decimal("10000.00")
    assert normalize_amount("1,234,56") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026/08/01", date(2026, 8, 1)),
        ("2026-8-1", date(2026, 8, 1)),
        ("20260801", date(2026, 8, 1)),
    ],
)
def test_normalize_date_accepts_common_statement_formats(raw: str, expected: date) -> None:
    assert normalize_date(raw) == expected


@pytest.mark.parametrize("raw", ["2026/99/01", "2026-02-31", "unknown"])
def test_normalize_date_rejects_invalid_dates(raw: str) -> None:
    assert normalize_date(raw) is None


def test_normalize_date_accepts_one_bounded_date_token_but_not_ambiguous_text() -> None:
    assert normalize_date("2025/08/21 经办用户:126636") == date(2025, 8, 21)
    assert normalize_date("2025/08/21 至 2025/08/22") is None
