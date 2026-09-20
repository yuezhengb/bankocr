from bankocr.parser.models import FieldValue, TransactionCandidate
from bankocr.parser.suggestions import suggest_candidate


def test_suggester_canonicalizes_known_types_without_touching_raw_or_final() -> None:
    candidate = TransactionCandidate(
        page_index=0,
        row_index=0,
        parser_id="test:v1",
        fields={
            "transaction_date": FieldValue("2026/8/1", "2026/8/1"),
            "amount": FieldValue("￥ 20.00", "￥ 20.00"),
            "description": FieldValue("  付款  ", "  付款  ", final_text="人工确认"),
        },
    )

    suggested = suggest_candidate(candidate)

    assert suggested.field("transaction_date").raw_text == "2026/8/1"
    assert suggested.field("transaction_date").suggested_text == "2026-08-01"
    assert suggested.field("amount").suggested_text == "20.00"
    assert suggested.field("description").suggested_text == "付款"
    assert suggested.field("description").final_text == "人工确认"
