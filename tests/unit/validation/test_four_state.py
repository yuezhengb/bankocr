from bankocr.parser.models import FieldValue, TransactionCandidate
from bankocr.validation.engine import (
    IssueSeverity,
    TransactionValidator,
    ValidationIssue,
    ValidationReport,
    ValidationRuleState,
)
from bankocr.validation.risk import ValidationStatus


def test_indeterminate_rule_requires_review_without_becoming_confirmed_failure():
    issue = ValidationIssue(
        code="missing_previous_balance",
        message="the preceding page does not contain a usable balance",
        severity=IssueSeverity.CRITICAL,
        row_index=0,
        field_name="balance",
        rule_state=ValidationRuleState.INDETERMINATE,
    )

    report = TransactionValidator().assess(
        ValidationReport(checked_rows=1, issues=(issue,), final_balances=()),
    )

    assert report.status is ValidationStatus.REVIEW
    assert report.risk_score < 100
    assert report.has_critical is False
    assert report.has_deterministic_failures is False
    assert "indeterminate:missing_previous_balance" in report.reasons


def test_not_applicable_rule_does_not_create_risk():
    issue = ValidationIssue(
        code="page_total_not_available",
        message="this statement format does not provide a page total",
        severity=IssueSeverity.CRITICAL,
        row_index=0,
        rule_state=ValidationRuleState.NOT_APPLICABLE,
    )

    report = TransactionValidator().assess(
        ValidationReport(checked_rows=1, issues=(issue,), final_balances=()),
    )

    assert report.status is ValidationStatus.PASS
    assert report.risk_score == 0
    assert report.reasons == ()


def test_unparseable_amount_is_explicitly_indeterminate():
    candidate = TransactionCandidate(
        page_index=0,
        row_index=0,
        parser_id="test:v1",
        fields={
            "transaction_amount": FieldValue("not-an-amount", "not-an-amount"),
            "balance": FieldValue("10.00", "10.00"),
        },
    )

    report = TransactionValidator().validate((candidate,))

    invalid_amount = next(issue for issue in report.issues if issue.code == "invalid_amount")
    assert invalid_amount.rule_state is ValidationRuleState.INDETERMINATE
