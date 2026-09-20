import pytest

from bankocr.benchmark.fields import FieldBenchmarkEvaluator, GoldenTransactionTruth
from bankocr.parser.models import FieldValue, TransactionCandidate


def _candidate(page: int, row: int, **fields: str) -> TransactionCandidate:
    return TransactionCandidate(
        page_index=page,
        row_index=row,
        parser_id="test:v1",
        fields={name: FieldValue(value, value) for name, value in fields.items()},
    )


def test_field_benchmark_reports_exact_accuracy_and_mismatches() -> None:
    predictions = (_candidate(0, 0, date="2026-08-01", amount="10.00"),)
    truths = (
        GoldenTransactionTruth(0, 0, {"date": "2026-08-01", "amount": "10.00", "balance": "10.00"}),
    )

    report = FieldBenchmarkEvaluator().evaluate(predictions, truths)

    assert report.total_fields == 3
    assert report.exact_matches == 2
    assert report.accuracy == pytest.approx(2 / 3)
    assert report.missing_predictions == ("0:0:balance",)


def test_field_benchmark_rejects_duplicate_keys() -> None:
    truth = GoldenTransactionTruth(0, 0, {"amount": "1.00"})

    with pytest.raises(ValueError):
        FieldBenchmarkEvaluator().evaluate((_candidate(0, 0, amount="1.00"),) * 2, (truth,))
