from decimal import Decimal

from bankocr.parser.models import FieldValue, TransactionCandidate
from bankocr.validation.engine import IssueSeverity, TransactionValidator, ValidationOptions


def _candidate(row: int, **values: str | None) -> TransactionCandidate:
    return TransactionCandidate(
        page_index=0,
        row_index=row,
        parser_id="test:v1",
        fields={
            name: FieldValue(raw_text=value or "", suggested_text=value)
            for name, value in values.items()
            if value not in (None, "")
        },
    )


def _candidate_at(page: int, row: int, **values: str | None) -> TransactionCandidate:
    return TransactionCandidate(
        page_index=page,
        row_index=row,
        parser_id="test:v1",
        fields={
            name: FieldValue(raw_text=value or "", suggested_text=value)
            for name, value in values.items()
            if value not in (None, "")
        },
    )


def test_validator_checks_decimal_balance_continuity_exactly() -> None:
    rows = (
        _candidate(0, transaction_date="2026-08-01", transaction_amount="10.00", balance="110.00"),
        _candidate(1, transaction_date="2026-08-02", transaction_amount="-5.00", balance="105.00"),
    )

    report = TransactionValidator().validate(rows)

    assert report.issues == ()
    assert report.checked_rows == 2
    assert report.final_balances[-1] == Decimal("105.00")


def test_validator_marks_balance_mismatch_as_critical_without_mutating_candidates() -> None:
    rows = (
        _candidate(0, transaction_date="2026-08-01", transaction_amount="10.00", balance="110.00"),
        _candidate(1, transaction_date="2026-08-02", transaction_amount="-5.00", balance="999.00"),
    )

    report = TransactionValidator().validate(rows)

    assert any(issue.code == "balance_mismatch" for issue in report.issues)
    assert any(issue.severity is IssueSeverity.CRITICAL for issue in report.issues)
    assert rows[1].field("balance").final_text is None


def test_validator_uses_income_minus_expense_for_split_amount_layout() -> None:
    rows = (
        _candidate(0, accounting_date="2026/08/01", income_amount="100.00", expense_amount="", online_balance="100.00"),
        _candidate(1, accounting_date="2026/08/02", income_amount="", expense_amount="30.00", online_balance="70.00"),
    )

    report = TransactionValidator().validate(rows)

    assert report.issues == ()


def test_validator_reports_unparseable_money_as_review_issue() -> None:
    rows = (_candidate(0, transaction_date="2026-08-01", transaction_amount="1O.00", balance="10.00"),)

    report = TransactionValidator().validate(rows)

    assert report.issues[0].code == "invalid_amount"
    assert report.issues[0].severity is IssueSeverity.ERROR


def test_validator_reports_non_monotonic_dates_and_duplicate_rows() -> None:
    rows = (
        _candidate(0, transaction_date="2026-08-01", transaction_amount="1.00", balance="1.00"),
        _candidate(1, transaction_date="2026-08-03", transaction_amount="1.00", balance="2.00"),
        _candidate(1, transaction_date="2026-08-02", transaction_amount="1.00", balance="3.00"),
    )

    report = TransactionValidator().validate(rows)

    assert any(issue.code == "duplicate_row" for issue in report.issues)
    assert any(issue.code == "date_order" for issue in report.issues)


def test_validator_rejects_malformed_currency_codes() -> None:
    row = _candidate(
        0,
        transaction_date="2026-08-01",
        transaction_amount="1.00",
        balance="1.00",
        currency="CN¥",
    )

    report = TransactionValidator().validate((row,))

    assert any(issue.code == "invalid_currency" for issue in report.issues)


def test_validator_reports_low_confidence_and_invalid_account_format() -> None:
    candidate = TransactionCandidate(
        page_index=0,
        row_index=0,
        parser_id="test:v1",
        fields={
            "transaction_date": FieldValue("2026-08-01", "2026-08-01", confidence=0.99),
            "transaction_amount": FieldValue("1.00", "1.00", confidence=0.99),
            "balance": FieldValue("1.00", "1.00", confidence=0.99),
            "counterparty_account": FieldValue("6222O", "6222O", confidence=0.40),
        },
    )

    report = TransactionValidator(
        ValidationOptions(min_field_confidence=0.80),
    ).validate((candidate,))

    assert any(issue.code == "low_confidence" for issue in report.issues)
    assert any(issue.code == "invalid_account" for issue in report.issues)


def test_validator_does_not_chain_balances_across_account_streams() -> None:
    rows = (
        _candidate(
            0,
            transaction_amount="100.00",
            balance="100.00",
            account_number="111111",
            currency="CNY",
        ),
        _candidate(
            1,
            transaction_amount="50.00",
            balance="50.00",
            account_number="222222",
            currency="CNY",
        ),
    )

    report = TransactionValidator().validate(rows)

    assert not any(issue.code == "balance_mismatch" for issue in report.issues)


def test_validator_checks_date_order_within_each_account_stream() -> None:
    rows = (
        _candidate(
            0,
            transaction_date="2026-08-01",
            transaction_amount="1.00",
            balance="1.00",
            account_number="111111",
        ),
        _candidate(
            1,
            transaction_date="2026-08-03",
            transaction_amount="1.00",
            balance="1.00",
            account_number="222222",
        ),
        _candidate(
            2,
            transaction_date="2026-08-02",
            transaction_amount="1.00",
            balance="2.00",
            account_number="111111",
        ),
    )

    report = TransactionValidator().validate(rows)

    assert not any(issue.code == "date_order" for issue in report.issues)


def test_validator_document_carries_balance_continuity_across_page_boundaries() -> None:
    rows = (
        _candidate_at(0, 0, transaction_date="2026-08-01", transaction_amount="100.00", balance="100.00"),
        _candidate_at(1, 0, transaction_date="2026-08-02", transaction_amount="-20.00", balance="80.00"),
        _candidate_at(1, 1, transaction_date="2026-08-03", transaction_amount="-10.00", balance="75.00"),
    )

    reports = TransactionValidator().validate_document(rows)

    assert not any(issue.code == "balance_mismatch" for issue in reports[0].issues)
    assert any(issue.code == "balance_mismatch" for issue in reports[1].issues)
    assert reports[0].final_balances == (Decimal("100.00"),)
    assert reports[1].final_balances == (Decimal("80.00"), Decimal("75.00"))


def test_validator_attaches_page_block_and_bbox_provenance_to_findings() -> None:
    from bankocr.domain.coordinates import Point
    from bankocr.domain.text_block import SourceType, TextBlock

    candidate = TransactionCandidate(
        page_index=2,
        row_index=4,
        parser_id="test:v1",
        fields={
            "transaction_date": FieldValue("bad-date", "bad-date", source_block_indices=(1,)),
            "transaction_amount": FieldValue("10.00", "10.00", source_block_indices=(2,)),
            "balance": FieldValue("10.00", "10.00", source_block_indices=(3,)),
        },
    )
    blocks = tuple(
        TextBlock(
            text=str(index),
            raw_text=str(index),
            polygon=(Point(index, 10), Point(index + 2, 10), Point(index + 2, 12), Point(index, 12)),
            confidence=0.9,
            source_type=SourceType.OCR,
            page_index=2,
            engine_id="test",
        )
        for index in range(4)
    )

    report = TransactionValidator().validate_document(
        (candidate,), blocks_by_page={2: blocks}
    )[2]

    issue = next(issue for issue in report.issues if issue.code == "invalid_date")
    assert issue.source_page_index == 2
    assert issue.source_block_indices == (1,)
    assert issue.source_bbox == (1, 10, 3, 12)
