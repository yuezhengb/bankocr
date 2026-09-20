"""Conservative normalization helpers; rejected values remain available as raw OCR."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import re
import unicodedata


_MONEY_RE = re.compile(r"^[+-]?(?:\d+)(?:\.\d{1,2})?$")
_GROUPED_INTEGER_RE = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})+$")
_DATE_SEPARATED_RE = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")
_DATE_COMPACT_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


def normalize_text(raw: str) -> str:
    if not isinstance(raw, str):
        raise TypeError("raw text must be a string")
    normalized = unicodedata.normalize("NFKC", raw)
    return " ".join(normalized.split())


def normalize_amount(raw: str) -> Decimal | None:
    text = normalize_text(raw).replace(" ", "")
    if not text:
        return None
    negative_parentheses = text.startswith("(") and text.endswith(")")
    if negative_parentheses:
        text = text[1:-1]
    for currency in ("￥", "¥", "CNY"):
        if text.startswith(currency):
            text = text[len(currency) :]
    text = _normalize_amount_separators(text)
    if text is None:
        return None
    if not _MONEY_RE.fullmatch(text):
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return -value if negative_parentheses else value


def _normalize_amount_separators(text: str) -> str | None:
    """Normalize thousands/decimal separators without guessing malformed OCR."""

    if "," not in text:
        return text
    if "." in text:
        # A decimal point already fixes the decimal separator.  Commas must
        # therefore be valid thousands separators, never arbitrary punctuation.
        if not _GROUPED_INTEGER_RE.fullmatch(text.split(".", 1)[0]):
            return None
        integer, fraction = text.split(".", 1)
        if not re.fullmatch(r"\d{1,2}", fraction):
            return None
        return integer.replace(",", "") + "." + fraction
    if text.count(",") > 1:
        return text.replace(",", "") if _GROUPED_INTEGER_RE.fullmatch(text) else None

    integer, fraction = text.split(",", 1)
    if not integer or not integer.lstrip("+-").isdigit() or not fraction.isdigit():
        return None
    if len(fraction) in (1, 2):
        return integer + "." + fraction
    if len(fraction) == 3:
        return text.replace(",", "")
    return None


def normalize_date(raw: str) -> date | None:
    text = normalize_text(raw).replace("年", "/").replace("月", "/").replace("日", "")
    separated = _DATE_SEPARATED_RE.fullmatch(text)
    compact = _DATE_COMPACT_RE.fullmatch(text)
    match = separated or compact
    if match is None:
        # OCR may merge the last date cell with a footer or a timestamp.  A
        # single, bounded date token is still deterministic; two possible
        # dates remain fail-closed.
        tokens = re.findall(r"(?<!\d)\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?!\d)", text)
        if len(tokens) == 1:
            match = _DATE_SEPARATED_RE.fullmatch(tokens[0])
    if match is None:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None
