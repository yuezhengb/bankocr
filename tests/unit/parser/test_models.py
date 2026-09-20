import pytest

from bankocr.parser.models import (
    CandidateStatus,
    FieldValue,
    ParserOutcome,
    ParserOutcomeStatus,
    TransactionCandidate,
)


def test_field_value_keeps_raw_suggestion_and_final_value_independent() -> None:
    value = FieldValue(
        raw_text="O.00",
        suggested_text="0.00",
        final_text=None,
        secondary_text="0.00",
        confidence=0.71,
        source_block_indices=(3,),
    )

    accepted = value.accept()
    corrected = value.accept("10.00")

    assert value.raw_text == "O.00"
    assert value.suggested_text == "0.00"
    assert value.secondary_text == "0.00"
    assert value.final_text is None
    assert accepted.final_text == "0.00"
    assert corrected.final_text == "10.00"
    assert corrected.raw_text == "O.00"
    assert corrected.suggested_text == "0.00"
    assert corrected.secondary_text == "0.00"


def test_transaction_candidate_does_not_promote_suggestions_implicitly() -> None:
    candidate = TransactionCandidate(
        page_index=0,
        row_index=4,
        parser_id="template:bank-b:v1",
        fields={
            "date": FieldValue("2026-08-01", "2026-08-01", confidence=0.99),
            "amount": FieldValue("1O.00", "10.00", confidence=0.72),
        },
    )

    assert candidate.status is CandidateStatus.UNREVIEWED
    assert candidate.field("amount").final_text is None
    reviewed = candidate.accept()

    assert reviewed.status is CandidateStatus.ACCEPTED
    assert reviewed.field("amount").final_text == "10.00"
    assert candidate.field("amount").final_text is None


def test_parser_outcome_can_fail_closed_without_returning_transactions() -> None:
    outcome = ParserOutcome.failed("no trusted template matched")

    assert outcome.status is ParserOutcomeStatus.FAILED
    assert outcome.candidates == ()
    assert outcome.reason == "no trusted template matched"


def test_parser_outcome_can_mark_an_ambiguous_page_for_review() -> None:
    outcome = ParserOutcome.page_review("generic columns are ambiguous")

    assert outcome.status is ParserOutcomeStatus.PAGE_REVIEW
    assert outcome.candidates == ()
    assert outcome.reason == "generic columns are ambiguous"


def test_field_value_rejects_invalid_confidence_and_source_indexes() -> None:
    with pytest.raises(ValueError):
        FieldValue("x", "x", confidence=1.1)
    with pytest.raises(ValueError):
        FieldValue("x", "x", source_block_indices=(-1,))
