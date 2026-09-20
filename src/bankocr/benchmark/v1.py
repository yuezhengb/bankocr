"""Golden-sample metrics and release thresholds for the V1 gate."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path
import time
from typing import Iterable

from bankocr.parser.models import CandidateStatus, TransactionCandidate
from bankocr.parser.normalization import normalize_amount, normalize_date
from bankocr.pipeline.processor import DocumentProcessor

from .fields import GoldenTransactionTruth
from .resources import peak_rss_mb


@dataclass(frozen=True, slots=True)
class V1Thresholds:
    transaction_recall: float = 0.995
    date_exact: float = 0.995
    amount_exact: float = 0.995
    balance_exact: float = 0.995
    row_association: float = 0.99
    review_rate: float = 0.10
    silent_critical_errors: int = 0
    peak_rss_mb: float = 6144.0


@dataclass(frozen=True, slots=True)
class V1Metrics:
    source_file: str
    source_sha256: str
    page_count: int
    truth_rows: int
    predicted_rows: int
    transaction_recall: float
    date_exact: float
    amount_exact: float
    balance_exact: float
    row_association: float
    review_rate: float
    silent_critical_errors: int
    elapsed_seconds: float
    peak_rss_mb: float
    gate_passed: bool
    gate_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["gate_reasons"] = list(self.gate_reasons)
        return result


class V1BenchmarkRunner:
    def __init__(self, processor: DocumentProcessor | None = None) -> None:
        self.processor = processor or DocumentProcessor()

    def run(
        self,
        source: str | Path,
        truths: Iterable[GoldenTransactionTruth],
        *,
        dpi: int = 200,
        thresholds: V1Thresholds | None = None,
    ) -> V1Metrics:
        source_path = Path(source)
        truth_values = tuple(truths)
        started = time.perf_counter()
        result = self.processor.process(source_path, dpi=dpi)
        elapsed = time.perf_counter() - started
        candidates = tuple(
            candidate for page in result.pages for candidate in page.parser_outcome.candidates
        )
        review_keys: set[tuple[int, int]] = set()
        for page in result.pages:
            report = page.validation_report
            status = None if report is None or report.status is None else report.status.value
            page_candidates = page.parser_outcome.candidates
            if status == "page_review":
                review_keys.update((item.page_index, item.row_index) for item in page_candidates)
            elif status == "review":
                issue_rows = {issue.row_index for issue in report.issues} if report is not None else set()
                if issue_rows:
                    review_keys.update((page.page_index, row_index) for row_index in issue_rows)
                else:
                    review_keys.update((item.page_index, item.row_index) for item in page_candidates)
        return evaluate_v1(
            source_path,
            len(result.pages),
            candidates,
            truth_values,
            elapsed_seconds=elapsed,
            peak_rss_mb=peak_rss_mb(),
            thresholds=thresholds,
            review_keys=frozenset(review_keys),
        )


def evaluate_v1(
    source: str | Path,
    page_count: int,
    predictions: tuple[TransactionCandidate, ...] | list[TransactionCandidate],
    truths: tuple[GoldenTransactionTruth, ...] | list[GoldenTransactionTruth],
    *,
    elapsed_seconds: float,
    peak_rss_mb: float,
    thresholds: V1Thresholds | None = None,
    review_keys: frozenset[tuple[int, int]] | set[tuple[int, int]] | None = None,
) -> V1Metrics:
    thresholds = thresholds or V1Thresholds()
    prediction_map = {(item.page_index, item.row_index): item for item in predictions}
    truth_map = {(item.page_index, item.row_index): item for item in truths}
    matched = set(prediction_map) & set(truth_map)
    truth_rows = len(truth_map)
    predicted_rows = len(prediction_map)

    def exact(field_names: tuple[str, ...]) -> float:
        expected: list[str] = []
        correct = 0
        for key, truth in truth_map.items():
            if not any(name in truth.fields for name in field_names):
                continue
            expected.append(key)
            actual = prediction_map.get(key)
            if actual is None:
                continue
            field_name = next(name for name in field_names if name in truth.fields)
            value = _field_text(actual, field_name)
            if value == truth.fields[field_name]:
                correct += 1
        return correct / len(expected) if expected else 0.0

    recall = len(matched) / truth_rows if truth_rows else 0.0
    association = len(matched) / max(truth_rows, predicted_rows, 1)
    if review_keys is None:
        review_rate = sum(
            candidate.status is not CandidateStatus.ACCEPTED for candidate in predictions
        ) / max(predicted_rows, 1)
    else:
        review_rate = sum(
            (candidate.page_index, candidate.row_index) in review_keys
            for candidate in predictions
        ) / max(predicted_rows, 1)
    silent = 0
    for key in matched:
        candidate = prediction_map[key]
        truth = truth_map[key]
        silently_passed = (
            candidate.status is CandidateStatus.ACCEPTED
            if review_keys is None
            else key not in review_keys
        )
        if silently_passed:
            for field_name in ("transaction_date", "accounting_date", "date", "amount", "transaction_amount", "balance", "online_balance"):
                expected = truth.fields.get(field_name)
                if expected is not None and _field_text(candidate, field_name) != expected:
                    silent += 1
                    break
    values = {
        "transaction_recall": recall,
        "date_exact": exact(("transaction_date", "accounting_date", "date")),
        "amount_exact": exact(("transaction_amount", "amount")),
        "balance_exact": exact(("balance", "online_balance")),
        "row_association": association,
    }
    reasons = [
        f"{name}<{getattr(thresholds, name):g}"
        for name, value in values.items()
        if value < getattr(thresholds, name)
    ]
    if review_rate > thresholds.review_rate:
        reasons.append(f"review_rate>{thresholds.review_rate:g}")
    if silent != thresholds.silent_critical_errors:
        reasons.append("silent_critical_errors!=0")
    if peak_rss_mb > thresholds.peak_rss_mb:
        reasons.append(f"peak_rss_mb>{thresholds.peak_rss_mb:g}")
    return V1Metrics(
        source_file=Path(source).name,
        source_sha256=_sha256(Path(source)),
        page_count=page_count,
        truth_rows=truth_rows,
        predicted_rows=predicted_rows,
        **values,
        review_rate=review_rate,
        silent_critical_errors=silent,
        elapsed_seconds=round(elapsed_seconds, 3),
        peak_rss_mb=round(peak_rss_mb, 2),
        gate_passed=not reasons,
        gate_reasons=tuple(reasons),
    )


def _field_text(candidate: TransactionCandidate, name: str) -> str | None:
    fields = dict(candidate.fields)
    aliases = {
        "transaction_date": ("transaction_date", "accounting_date", "date"),
        "accounting_date": ("accounting_date", "transaction_date", "date"),
        "date": ("date", "transaction_date", "accounting_date"),
        "balance": ("balance", "online_balance", "closing_balance"),
        "online_balance": ("online_balance", "balance", "closing_balance"),
        "closing_balance": ("closing_balance", "balance", "online_balance"),
        "transaction_amount": ("transaction_amount", "amount"),
        "amount": ("amount", "transaction_amount"),
    }
    for alias in aliases.get(name, (name,)):
        field = fields.get(alias)
        if field is not None:
            return _normalize_benchmark_value(name, field.final_text or field.suggested_text or field.raw_text)
    if name in {"transaction_amount", "amount"}:
        derived = _derive_net_amount(fields)
        if derived is not None:
            return f"{derived:.2f}"
    return None


def _normalize_benchmark_value(name: str, value: str) -> str:
    if name in {"transaction_date", "accounting_date", "date"}:
        parsed_date = normalize_date(value)
        return parsed_date.isoformat() if parsed_date is not None else value
    if name in {
        "amount",
        "transaction_amount",
        "balance",
        "online_balance",
        "opening_balance",
        "closing_balance",
        "income_amount",
        "expense_amount",
    }:
        parsed_amount = normalize_amount(value)
        return f"{parsed_amount:.2f}" if parsed_amount is not None else value
    return value


def _derive_net_amount(fields: dict[str, object]) -> Decimal | None:
    income = _amount_from_fields(fields, ("income_amount", "income"))
    expense = _amount_from_fields(fields, ("expense_amount", "expense"))
    if income is None and expense is None:
        return None
    return (income or Decimal("0")) - (expense or Decimal("0"))


def _amount_from_fields(fields: dict[str, object], names: tuple[str, ...]) -> Decimal | None:
    for name in names:
        field = fields.get(name)
        if field is None:
            continue
        value = getattr(field, "final_text", None) or getattr(field, "suggested_text", None) or getattr(field, "raw_text", None)
        if not isinstance(value, str):
            continue
        parsed = normalize_amount(value)
        if parsed is not None:
            return parsed
        try:
            return Decimal(value)
        except (InvalidOperation, ValueError):
            return None
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
