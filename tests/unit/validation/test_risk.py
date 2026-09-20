from bankocr.parser.models import CandidateStatus, FieldValue, TransactionCandidate
from bankocr.validation.engine import IssueSeverity, ValidationIssue, ValidationReport
from bankocr.validation.risk import RiskScorer, ValidationStatus


def _candidate(*, accepted: bool = True, normalized: bool = False) -> TransactionCandidate:
    raw = "1O.00" if normalized else "10.00"
    candidate = TransactionCandidate(
        page_index=0,
        row_index=0,
        parser_id="test:v1",
        fields={"amount": FieldValue(raw, "10.00")},
    )
    return candidate.accept() if accepted else candidate


def test_risk_scorer_distinguishes_pass_normalization_review_and_page_review() -> None:
    scorer = RiskScorer()
    assert scorer.assess((), (_candidate(),)).status is ValidationStatus.PASS
    assert scorer.assess((), (_candidate(normalized=True),)).status is ValidationStatus.PASS_WITH_NORMALIZATION
    assert scorer.assess((), (_candidate(accepted=False),)).status is ValidationStatus.PASS
    assert scorer.assess((), (_candidate().reject(),)).status is ValidationStatus.REVIEW
    assert scorer.assess((), (), parser_status="page_review").status is ValidationStatus.PAGE_REVIEW


def test_critical_validation_issue_is_review_with_maximum_score() -> None:
    issue = ValidationIssue("balance_mismatch", "bad", IssueSeverity.CRITICAL, 2, "balance")
    assessment = RiskScorer().assess((issue,))
    assert assessment.status is ValidationStatus.REVIEW
    assert assessment.score == 100
    assert assessment.reasons == ("critical:balance_mismatch",)


def test_validation_report_defaults_are_deterministic() -> None:
    report = ValidationReport(1, (), ())
    assert report.status is ValidationStatus.PASS
    assert report.risk_score == 0
