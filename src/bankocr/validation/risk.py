"""Deterministic risk/status scoring for parser and validation results."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class ValidationStatus(str, Enum):
    PASS = "pass"
    PASS_WITH_NORMALIZATION = "pass_with_normalization"
    REVIEW = "review"
    PAGE_REVIEW = "page_review"


class ValidationRuleState(str, Enum):
    """State of one deterministic rule, distinct from page risk status."""

    PASS = "pass"
    FAIL = "fail"
    INDETERMINATE = "indeterminate"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    status: ValidationStatus
    score: int
    reasons: tuple[str, ...]


class RiskScorer:
    """Score only observable facts; no random or model-dependent decisions."""

    def assess(
        self,
        issues: Iterable[object],
        candidates: Iterable[object] = (),
        *,
        parser_status: object | None = None,
        page_error: str | None = None,
    ) -> RiskAssessment:
        issue_values = tuple(issues)
        candidate_values = tuple(candidates)
        status_value = getattr(parser_status, "value", parser_status)
        reasons: list[str] = []

        if page_error or status_value in {"failed", "page_review"}:
            if page_error:
                reasons.append("page_error")
            if status_value:
                reasons.append(f"parser:{status_value}")
            return RiskAssessment(ValidationStatus.PAGE_REVIEW, 100, tuple(dict.fromkeys(reasons)))

        applicable_issues = tuple(
            issue
            for issue in issue_values
            if getattr(issue, "rule_state", ValidationRuleState.FAIL)
            not in {ValidationRuleState.NOT_APPLICABLE, ValidationRuleState.PASS}
        )
        deterministic = tuple(
            issue
            for issue in applicable_issues
            if getattr(issue, "rule_state", ValidationRuleState.FAIL)
            is ValidationRuleState.FAIL
        )
        indeterminate = tuple(
            issue
            for issue in applicable_issues
            if getattr(issue, "rule_state", ValidationRuleState.FAIL)
            is ValidationRuleState.INDETERMINATE
        )
        critical = any(
            getattr(issue, "severity", None).value == "critical"
            for issue in deterministic
        )
        if critical:
            reasons.extend(
                f"critical:{getattr(issue, 'code', 'unknown')}"
                for issue in deterministic
                if getattr(getattr(issue, "severity", None), "value", None) == "critical"
            )
            return RiskAssessment(ValidationStatus.REVIEW, 100, tuple(dict.fromkeys(reasons)))

        if deterministic:
            reasons.extend(f"issue:{getattr(issue, 'code', 'unknown')}" for issue in deterministic)
            return RiskAssessment(ValidationStatus.REVIEW, min(99, 40 * len(deterministic)), tuple(dict.fromkeys(reasons)))

        if indeterminate:
            reasons.extend(
                f"indeterminate:{getattr(issue, 'code', 'unknown')}"
                for issue in indeterminate
            )
            return RiskAssessment(
                ValidationStatus.REVIEW,
                min(80, 20 * len(indeterminate)),
                tuple(dict.fromkeys(reasons)),
            )

        rejected = any(
            getattr(getattr(candidate, "status", None), "value", None) == "rejected"
            for candidate in candidate_values
        )
        if rejected:
            return RiskAssessment(ValidationStatus.REVIEW, 80, ("candidate_rejected",))

        normalized = any(
            field.raw_text != (field.suggested_text or field.raw_text)
            for candidate in candidate_values
            for _, field in candidate.fields
        )
        if normalized:
            return RiskAssessment(ValidationStatus.PASS_WITH_NORMALIZATION, 10, ("normalized_value",))
        return RiskAssessment(ValidationStatus.PASS, 0, ())
