from decimal import Decimal

from bankocr.parser.models import CandidateStatus, FieldValue, TransactionCandidate
from bankocr.transaction.builder import TransactionBuilder


def _candidate(page: int, row: int, account: str, date: str) -> TransactionCandidate:
    return TransactionCandidate(
        page_index=page,
        row_index=row,
        parser_id="layout:v1",
        fields={
            "account_number": FieldValue(account, account),
            "currency": FieldValue("CNY", "CNY"),
            "transaction_date": FieldValue(date, date),
            "transaction_amount": FieldValue("10,00", "10.00"),
            "balance": FieldValue("110.00", "110.00"),
        },
    )


def test_transaction_builder_keeps_accounts_separate_and_preserves_same_date_rows() -> None:
    records = TransactionBuilder().build(
        (_candidate(0, 1, "10000001", "2026/08/01"), _candidate(1, 0, "20000002", "2026/08/01"))
    )

    assert len({record.statement_stream_id for record in records}) == 2
    assert records[0].transaction_date is not None
    assert records[0].amount == Decimal("10.00")
    assert records[0].transaction_id != records[1].transaction_id


def test_transaction_builder_accepts_explicit_section_boundaries() -> None:
    candidate = _candidate(0, 0, "10000001", "2026/08/01")
    records = TransactionBuilder().build(
        (candidate,), stream_overrides={(0, 0): "document-section-2"}
    )
    assert records[0].statement_stream_id.startswith("stream-")


def test_transaction_builder_uses_review_order_and_excludes_marked_duplicates() -> None:
    first = _candidate(0, 0, "10000001", "2026/08/01")
    second = _candidate(0, 1, "10000001", "2026/08/02")
    moved = TransactionCandidate(
        page_index=second.page_index,
        row_index=second.row_index,
        parser_id=second.parser_id,
        fields=second.fields,
        review_order=0,
    )
    duplicate = first.mark_duplicate((0, 1))

    records = TransactionBuilder().build((duplicate, moved))

    assert len(records) == 1
    assert records[0].candidate.row_index == 1
    assert records[0].candidate.status is not CandidateStatus.DUPLICATE
