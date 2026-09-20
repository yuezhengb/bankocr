from pathlib import Path

from bankocr.benchmark.fields import GoldenTransactionTruth
from bankocr.benchmark.v1 import V1Thresholds, evaluate_v1
from bankocr.parser.models import FieldValue, TransactionCandidate


def test_v1_metrics_calculate_recall_exact_fields_and_review_rate(tmp_path: Path) -> None:
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"fixture")
    candidate = TransactionCandidate(
        page_index=0,
        row_index=0,
        parser_id="known:v1",
        fields={
            "transaction_date": FieldValue("2026/08/01", "2026-08-01"),
            "transaction_amount": FieldValue("10.00", "10.00"),
            "balance": FieldValue("10.00", "10.00"),
        },
    )
    result = evaluate_v1(
        source,
        1,
        (candidate,),
        (GoldenTransactionTruth(0, 0, {"transaction_date": "2026-08-01", "transaction_amount": "10.00", "balance": "10.00"}),),
        elapsed_seconds=1.2,
        peak_rss_mb=10.0,
    )
    assert result.transaction_recall == 1.0
    assert result.date_exact == 1.0
    assert result.gate_passed is False
    assert "review_rate>0.1" in result.gate_reasons


def test_v1_metrics_compare_template_specific_aliases_and_derive_net_amount(tmp_path: Path) -> None:
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"fixture")
    candidate = TransactionCandidate(
        page_index=0,
        row_index=0,
        parser_id="known:online-v1",
        fields={
            "accounting_date": FieldValue("2025/08/19", "2025-08-19"),
            "income_amount": FieldValue("0.00", "0.00"),
            "expense_amount": FieldValue("43.54", "43.54"),
            "online_balance": FieldValue("196.03", "196.03"),
        },
    )
    result = evaluate_v1(
        source,
        1,
        (candidate,),
        (
            GoldenTransactionTruth(
                0,
                0,
                {
                    "transaction_date": "2025-08-19",
                    "transaction_amount": "-43.54",
                    "balance": "196.03",
                },
            ),
        ),
        elapsed_seconds=0.1,
        peak_rss_mb=10.0,
    )
    assert result.transaction_recall == 1.0
    assert result.date_exact == 1.0
    assert result.amount_exact == 1.0
    assert result.balance_exact == 1.0


def test_v1_review_rate_uses_deterministic_risk_queue_not_human_final_state(tmp_path: Path) -> None:
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"fixture")
    candidate = TransactionCandidate(
        page_index=0,
        row_index=0,
        parser_id="known:v1",
        fields={
            "transaction_date": FieldValue("2026-08-01", "2026-08-01"),
            "transaction_amount": FieldValue("10.00", "10.00"),
            "balance": FieldValue("10.00", "10.00"),
        },
    )
    result = evaluate_v1(
        source,
        1,
        (candidate,),
        (GoldenTransactionTruth(0, 0, {"transaction_date": "2026-08-01", "transaction_amount": "10.00", "balance": "10.00"}),),
        elapsed_seconds=0.1,
        peak_rss_mb=10.0,
        review_keys=frozenset(),
    )
    assert result.review_rate == 0.0
    assert result.silent_critical_errors == 0
    assert result.gate_passed is True


def test_v1_gate_rejects_processes_over_the_memory_ceiling(tmp_path: Path) -> None:
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"fixture")
    result = evaluate_v1(
        source,
        0,
        (),
        (),
        elapsed_seconds=0.1,
        peak_rss_mb=20.0,
        thresholds=V1Thresholds(
            transaction_recall=0,
            date_exact=0,
            amount_exact=0,
            balance_exact=0,
            row_association=0,
            peak_rss_mb=10.0,
        ),
        review_keys=frozenset(),
    )
    assert result.gate_passed is False
    assert "peak_rss_mb>10" in result.gate_reasons
