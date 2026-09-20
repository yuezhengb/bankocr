"""Fail-closed financial checks using Decimal rather than floating point."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from enum import Enum
import re
from collections import defaultdict
from typing import Mapping, Sequence

from bankocr.domain.text_block import TextBlock
from bankocr.parser.models import FieldValue, TransactionCandidate
from bankocr.parser.normalization import normalize_amount, normalize_date
from .risk import RiskScorer, ValidationRuleState, ValidationStatus


class IssueSeverity(str, Enum):
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class ValidationOptions:
    min_field_confidence: float = 0.80
    check_date_order: bool = True
    check_duplicate_rows: bool = True
    check_account_format: bool = True
    check_currency_format: bool = True

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_field_confidence <= 1.0:
            raise ValueError("min_field_confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str
    severity: IssueSeverity
    row_index: int
    field_name: str | None = None
    source_page_index: int | None = None
    source_block_indices: tuple[int, ...] = ()
    source_bbox: tuple[float, float, float, float] | None = None
    rule_state: ValidationRuleState = ValidationRuleState.FAIL


@dataclass(frozen=True, slots=True)
class ValidationReport:
    checked_rows: int
    issues: tuple[ValidationIssue, ...]
    final_balances: tuple[Decimal | None, ...]
    status: ValidationStatus | None = None
    risk_score: int | None = None
    reasons: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.checked_rows < 0:
            raise ValueError("checked_rows must be non-negative")
        if self.status is None:
            status = (
                ValidationStatus.REVIEW
                if any(
                    issue.rule_state not in {
                        ValidationRuleState.PASS,
                        ValidationRuleState.NOT_APPLICABLE,
                    }
                    for issue in self.issues
                )
                else ValidationStatus.PASS
            )
            object.__setattr__(self, "status", status)
        if self.risk_score is None:
            score = (
                100
                if self.has_critical
                else 40
                if self.has_deterministic_failures
                else 20
                if self.has_indeterminate
                else 0
            )
            object.__setattr__(self, "risk_score", score)
        if self.reasons is None:
            object.__setattr__(
                self,
                "reasons",
                tuple(dict.fromkeys(issue.code for issue in self.issues)),
            )

    @property
    def passed(self) -> bool:
        return not (self.has_deterministic_failures or self.has_indeterminate)

    @property
    def has_critical(self) -> bool:
        return any(
            issue.severity is IssueSeverity.CRITICAL
            and issue.rule_state is ValidationRuleState.FAIL
            for issue in self.issues
        )

    @property
    def has_deterministic_failures(self) -> bool:
        return any(issue.rule_state is ValidationRuleState.FAIL for issue in self.issues)

    @property
    def has_indeterminate(self) -> bool:
        return any(
            issue.rule_state is ValidationRuleState.INDETERMINATE
            for issue in self.issues
        )


class TransactionValidator:
    """Validate parsed suggestions without promoting them to final values."""

    def __init__(self, options: ValidationOptions | None = None) -> None:
        self.options = options or ValidationOptions()
        self.risk_scorer = RiskScorer()

    def assess(
        self,
        report: ValidationReport,
        candidates: tuple[TransactionCandidate, ...] | list[TransactionCandidate] = (),
        *,
        parser_status: object | None = None,
        page_error: str | None = None,
    ) -> ValidationReport:
        assessment = self.risk_scorer.assess(
            report.issues,
            candidates,
            parser_status=parser_status,
            page_error=page_error,
        )
        return replace(
            report,
            status=assessment.status,
            risk_score=assessment.score,
            reasons=assessment.reasons,
        )

    def validate(self, candidates: tuple[TransactionCandidate, ...] | list[TransactionCandidate]) -> ValidationReport:
        """Validate one page or return a combined report for a document."""

        reports = self.validate_document(candidates)
        if not reports:
            return ValidationReport(checked_rows=0, issues=(), final_balances=())
        if len(reports) == 1:
            return next(iter(reports.values()))
        return self.assess(ValidationReport(
            checked_rows=sum(report.checked_rows for report in reports.values()),
            issues=tuple(
                issue
                for page_index in sorted(reports)
                for issue in reports[page_index].issues
            ),
            final_balances=tuple(
                balance
                for page_index in sorted(reports)
                for balance in reports[page_index].final_balances
            ),
        ), candidates)

    def validate_document(
        self,
        candidates: tuple[TransactionCandidate, ...] | list[TransactionCandidate],
        *,
        blocks_by_page: Mapping[int, Sequence[TextBlock]] | None = None,
    ) -> dict[int, ValidationReport]:
        """Validate all pages in one ordered stream.

        The per-page reports retain the global balance/date context, so a
        transaction on page N is checked against the final balance on page
        N-1 instead of silently starting a new chain.
        """

        ordered = tuple(sorted(candidates, key=lambda candidate: (candidate.page_index, candidate.row_index)))
        issues: list[ValidationIssue] = []
        issues_by_page: dict[int, list[ValidationIssue]] = defaultdict(list)
        balances: list[Decimal | None] = []
        balances_by_page: dict[int, list[Decimal | None]] = defaultdict(list)
        rows_by_page: dict[int, int] = defaultdict(int)
        previous_balances: dict[tuple[str, str], Decimal] = {}
        seen_rows: set[tuple[int, int]] = set()
        parsed_dates: dict[tuple[str, str], list[tuple[int, int, date]]] = defaultdict(list)

        for candidate in ordered:
            rows_by_page[candidate.page_index] += 1
            page_issues: list[ValidationIssue] = []
            stream_key = _stream_key(candidate)
            key = (candidate.page_index, candidate.row_index)
            if self.options.check_duplicate_rows and key in seen_rows:
                page_issues.append(
                    ValidationIssue(
                        code="duplicate_row",
                        message="page and row key occurs more than once",
                        severity=IssueSeverity.CRITICAL,
                        row_index=candidate.row_index,
                    )
                )
            seen_rows.add(key)
            parsed_date = self._validate_date(candidate, page_issues)
            if parsed_date is not None:
                parsed_dates[stream_key].append(
                    (candidate.page_index, candidate.row_index, parsed_date)
                )
            self._validate_confidence(candidate, page_issues)
            if self.options.check_account_format:
                self._validate_account(candidate, page_issues)
            if self.options.check_currency_format:
                self._validate_currency(candidate, page_issues)
            amount = self._transaction_amount(candidate, page_issues)
            balance = self._field_amount(candidate, "balance", page_issues)
            if balance is None:
                balance = self._field_amount(candidate, "online_balance", page_issues)
            if balance is None:
                page_issues.append(
                    ValidationIssue(
                        code="invalid_balance",
                        message="balance is missing or cannot be parsed as Decimal",
                        severity=IssueSeverity.ERROR,
                        row_index=candidate.row_index,
                        field_name="balance",
                        rule_state=ValidationRuleState.INDETERMINATE,
                    )
                )

            previous_balance = previous_balances.get(stream_key)
            if previous_balance is not None and amount is not None and balance is not None:
                if previous_balance + amount != balance:
                    page_issues.append(
                        ValidationIssue(
                            code="balance_mismatch",
                            message=(
                                f"expected {previous_balance + amount} from previous balance and amount, "
                                f"got {balance}"
                            ),
                            severity=IssueSeverity.CRITICAL,
                            row_index=candidate.row_index,
                            field_name="balance",
                        )
                    )
                    page_issues.append(
                        ValidationIssue(
                            code="possible_missing_transaction",
                            message=(
                                "balance continuity leaves an unexplained delta; "
                                "a row may be missing or a critical amount may be wrong"
                            ),
                            severity=IssueSeverity.ERROR,
                            row_index=candidate.row_index,
                            field_name="transaction_amount",
                            rule_state=ValidationRuleState.INDETERMINATE,
                        )
                    )
            balances.append(balance)
            balances_by_page[candidate.page_index].append(balance)
            if balance is None:
                previous_balances.pop(stream_key, None)
            else:
                previous_balances[stream_key] = balance
            issues.extend(page_issues)
            issues_by_page[candidate.page_index].extend(page_issues)

        if self.options.check_date_order:
            for dates in parsed_dates.values():
                self._validate_date_order_by_page(dates, issues_by_page, issues)

        candidate_by_key = {
            (candidate.page_index, candidate.row_index): candidate
            for candidate in ordered
        }
        for page_index, page_issues in tuple(issues_by_page.items()):
            issues_by_page[page_index] = [
                self._attach_provenance(issue, page_index, candidate_by_key, blocks_by_page)
                for issue in page_issues
            ]

        candidates_by_page: dict[int, list[TransactionCandidate]] = defaultdict(list)
        for candidate in ordered:
            candidates_by_page[candidate.page_index].append(candidate)
        return {
            page_index: self.assess(
                ValidationReport(
                    checked_rows=rows_by_page[page_index],
                    issues=tuple(issues_by_page.get(page_index, ())),
                    final_balances=tuple(balances_by_page.get(page_index, ())),
                ),
                candidates_by_page[page_index],
            )
            for page_index in sorted(rows_by_page)
        }

    @staticmethod
    def _attach_provenance(
        issue: ValidationIssue,
        page_index: int,
        candidates: Mapping[tuple[int, int], TransactionCandidate],
        blocks_by_page: Mapping[int, Sequence[TextBlock]] | None,
    ) -> ValidationIssue:
        if issue.source_page_index is not None:
            return issue
        candidate = candidates.get((page_index, issue.row_index))
        if candidate is None:
            candidate = next(
                (
                    value
                    for (candidate_page, _), value in candidates.items()
                    if candidate_page == page_index and value.row_index == issue.row_index
                ),
                None,
            )
        if candidate is None:
            return issue
        field = _field(candidate, issue.field_name) if issue.field_name else None
        indices = field.source_block_indices if field is not None else ()
        bbox = _bbox(candidate.page_index, indices, blocks_by_page)
        return replace(
            issue,
            source_page_index=candidate.page_index,
            source_block_indices=indices,
            source_bbox=bbox,
        )

    def _validate_date(
        self,
        candidate: TransactionCandidate,
        issues: list[ValidationIssue],
    ) -> date | None:
        for name in ("transaction_date", "accounting_date", "date"):
            value = _field(candidate, name)
            if value is None:
                continue
            parsed = normalize_date(_effective_text(value))
            if parsed is None:
                issues.append(
                ValidationIssue(
                    code="invalid_date",
                    message="date cannot be normalized deterministically",
                    severity=IssueSeverity.ERROR,
                    row_index=candidate.row_index,
                    field_name=name,
                    rule_state=ValidationRuleState.INDETERMINATE,
                )
                )
            return parsed
        return None

    def _validate_confidence(
        self,
        candidate: TransactionCandidate,
        issues: list[ValidationIssue],
    ) -> None:
        for name, value in candidate.fields:
            if value.confidence is not None and value.confidence < self.options.min_field_confidence:
                issues.append(
                    ValidationIssue(
                        code="low_confidence",
                        message=(
                            f"field confidence {value.confidence:.3f} is below "
                            f"{self.options.min_field_confidence:.3f}"
                        ),
                        severity=IssueSeverity.ERROR,
                        row_index=candidate.row_index,
                        field_name=name,
                        rule_state=ValidationRuleState.INDETERMINATE,
                    )
                )

    def _validate_account(
        self,
        candidate: TransactionCandidate,
        issues: list[ValidationIssue],
    ) -> None:
        for name in ("counterparty_account", "account_number", "account"):
            value = _field(candidate, name)
            if value is None:
                continue
            compact = re.sub(r"[\s-]", "", _effective_text(value))
            if not re.fullmatch(r"\d{6,30}", compact):
                issues.append(
                    ValidationIssue(
                        code="invalid_account",
                        message="account contains non-digit characters or has an implausible length",
                        severity=IssueSeverity.ERROR,
                        row_index=candidate.row_index,
                        field_name=name,
                        rule_state=ValidationRuleState.INDETERMINATE,
                    )
                )
            return

    def _validate_currency(
        self,
        candidate: TransactionCandidate,
        issues: list[ValidationIssue],
    ) -> None:
        for name in ("currency", "currency_code"):
            value = _field(candidate, name)
            if value is None:
                continue
            compact = re.sub(r"\s+", "", _effective_text(value)).upper()
            if compact in {"RMB", "人民币", "人民币元"}:
                return
            if not re.fullmatch(r"[A-Z]{3}", compact):
                issues.append(
                    ValidationIssue(
                        code="invalid_currency",
                        message="currency must be a three-letter code or a supported RMB label",
                        severity=IssueSeverity.ERROR,
                        row_index=candidate.row_index,
                        field_name=name,
                        rule_state=ValidationRuleState.INDETERMINATE,
                    )
                )
            return

    def _validate_date_order(
        self,
        parsed_dates: list[tuple[int, date]],
        issues: list[ValidationIssue],
    ) -> None:
        if len(parsed_dates) < 2:
            return
        _, previous_date = parsed_dates[0]
        direction = 0
        for row_index, current_date in parsed_dates[1:]:
            if direction == 0 and current_date != previous_date:
                direction = 1 if current_date > previous_date else -1
            elif direction == 1 and current_date < previous_date:
                issues.append(
                    ValidationIssue(
                        code="date_order",
                        message="transaction dates are not monotonic in ascending order",
                        severity=IssueSeverity.ERROR,
                        row_index=row_index,
                        field_name="date",
                    )
                )
            elif direction == -1 and current_date > previous_date:
                issues.append(
                    ValidationIssue(
                        code="date_order",
                        message="transaction dates are not monotonic in descending order",
                        severity=IssueSeverity.ERROR,
                        row_index=row_index,
                        field_name="date",
                    )
                )
            previous_date = current_date

    def _validate_date_order_by_page(
        self,
        parsed_dates: list[tuple[int, int, date]],
        issues_by_page: dict[int, list[ValidationIssue]],
        combined_issues: list[ValidationIssue],
    ) -> None:
        if len(parsed_dates) < 2:
            return
        _, previous_date = parsed_dates[0][1], parsed_dates[0][2]
        direction = 0
        for page_index, row_index, current_date in parsed_dates[1:]:
            issue: ValidationIssue | None = None
            if direction == 0 and current_date != previous_date:
                direction = 1 if current_date > previous_date else -1
            elif direction == 1 and current_date < previous_date:
                issue = ValidationIssue(
                    code="date_order",
                    message="transaction dates are not monotonic in ascending order",
                    severity=IssueSeverity.ERROR,
                    row_index=row_index,
                    field_name="date",
                )
            elif direction == -1 and current_date > previous_date:
                issue = ValidationIssue(
                    code="date_order",
                    message="transaction dates are not monotonic in descending order",
                    severity=IssueSeverity.ERROR,
                    row_index=row_index,
                    field_name="date",
                )
            if issue is not None:
                issues_by_page[page_index].append(issue)
                combined_issues.append(issue)
            previous_date = current_date

    def _transaction_amount(
        self,
        candidate: TransactionCandidate,
        issues: list[ValidationIssue],
    ) -> Decimal | None:
        direct = _field(candidate, "transaction_amount") or _field(candidate, "amount")
        if direct is not None:
            return self._field_amount_value(candidate, direct, "transaction_amount", issues)

        income = self._field_amount(candidate, "income_amount", issues)
        expense = self._field_amount(candidate, "expense_amount", issues)
        if income is None and expense is None:
            issues.append(
                ValidationIssue(
                    code="missing_amount",
                    message="neither transaction amount nor income/expense amount is available",
                    severity=IssueSeverity.ERROR,
                    row_index=candidate.row_index,
                    field_name="amount",
                    rule_state=ValidationRuleState.INDETERMINATE,
                )
            )
            return None
        return (income or Decimal("0")) - (expense or Decimal("0"))

    def _field_amount(
        self,
        candidate: TransactionCandidate,
        name: str,
        issues: list[ValidationIssue],
    ) -> Decimal | None:
        value = _field(candidate, name)
        if value is None:
            return None
        return self._field_amount_value(candidate, value, name, issues)

    def _field_amount_value(
        self,
        candidate: TransactionCandidate,
        value: FieldValue,
        name: str,
        issues: list[ValidationIssue],
    ) -> Decimal | None:
        parsed = normalize_amount(_effective_text(value))
        if parsed is None:
            issues.append(
                ValidationIssue(
                    code="invalid_amount",
                    message="amount cannot be normalized deterministically",
                    severity=IssueSeverity.ERROR,
                    row_index=candidate.row_index,
                    field_name=name,
                    rule_state=ValidationRuleState.INDETERMINATE,
                )
            )
        return parsed


def _field(candidate: TransactionCandidate, name: str) -> FieldValue | None:
    try:
        return candidate.field(name)
    except KeyError:
        return None


def _effective_text(value: FieldValue) -> str:
    return value.final_text if value.final_text is not None else (value.suggested_text or "")


def _stream_key(candidate: TransactionCandidate) -> tuple[str, str]:
    stream_id = ""
    for name in ("statement_stream_id", "stream_id"):
        value = _field(candidate, name)
        if value is not None:
            stream_id = re.sub(r"\s+", "", _effective_text(value))
            break
    account = ""
    for name in ("account_number", "account_id", "own_account", "account"):
        value = _field(candidate, name)
        if value is not None:
            account = re.sub(r"\s+", "", _effective_text(value))
            break
    currency = ""
    for name in ("currency", "currency_code"):
        value = _field(candidate, name)
        if value is not None:
            currency = _effective_text(value).casefold()
            break
    return f"{stream_id}\x1f{account}", currency


def _bbox(
    page_index: int,
    indices: tuple[int, ...],
    blocks_by_page: Mapping[int, Sequence[TextBlock]] | None,
) -> tuple[float, float, float, float] | None:
    if not blocks_by_page or not indices:
        return None
    blocks = blocks_by_page.get(page_index, ())
    boxes = [blocks[index].bbox for index in indices if 0 <= index < len(blocks)]
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )
