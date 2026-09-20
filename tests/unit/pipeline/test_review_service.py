from decimal import Decimal
from pathlib import Path

from bankocr.domain.run_manifest import RunManifest
from bankocr.gui.review_model import ReviewSession
from bankocr.parser.models import FieldValue, TransactionCandidate
from bankocr.pipeline.review_service import ReviewService
from bankocr.storage.project_store import ProjectStore
from bankocr.validation.engine import IssueSeverity, ValidationIssue, ValidationReport


def _manifest() -> RunManifest:
    return RunManifest(
        app_version="0.1.0",
        project_schema_version="1",
        ocr_engine="test",
        ocr_model_id="test",
        model_sha256="a" * 64,
        execution_provider="cpu",
        preprocess_profile="test",
        parser_version="test",
        template_version="test",
        validation_rules_version="test",
        exporter_version="test",
    )


def _candidate() -> TransactionCandidate:
    return TransactionCandidate(
        page_index=0,
        row_index=0,
        parser_id="test:v1",
        fields={
            "transaction_date": FieldValue("2026-08-01", "2026-08-01"),
            "transaction_amount": FieldValue("1.00", "1.00"),
            "balance": FieldValue("1.00", "1.00"),
        },
    )


def test_review_service_revalidates_final_values_before_persisting(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")
    run_id = store.create_run(project_id, _manifest())
    candidate = _candidate()
    store.save_candidates(run_id, (candidate,))
    store.save_validation_report(
        run_id,
        0,
        ValidationReport(
            checked_rows=1,
            issues=(
                ValidationIssue(
                    code="invalid_amount",
                    message="old report",
                    severity=IssueSeverity.ERROR,
                    row_index=0,
                    field_name="transaction_amount",
                ),
            ),
            final_balances=(Decimal("1.00"),),
        ),
    )
    store.save_page_state(run_id, 0, "needs_review")
    store.set_run_status(run_id, "needs_review")

    ReviewService(store).save(run_id, (candidate.accept(),))

    assert store.load_validation_reports(run_id)[0].issues == ()
    assert store.get_run_status(run_id) == "completed"
    store.close()


def test_review_service_persists_structure_session_and_operations(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")
    run_id = store.create_run(project_id, _manifest())
    first = _candidate()
    second = TransactionCandidate(
        page_index=0,
        row_index=1,
        parser_id="test:v1",
        fields={
            "transaction_date": FieldValue("2026-08-02", "2026-08-02"),
            "transaction_amount": FieldValue("2.00", "2.00"),
            "balance": FieldValue("3.00", "3.00"),
        },
    )
    store.save_candidates(run_id, (first, second))
    store.save_page_state(run_id, 0, "needs_review")
    store.set_run_status(run_id, "needs_review")

    session = ReviewSession((first, second)).mark_duplicate(1, 0)
    ReviewService(store).save_session(run_id, session, reviewer="reviewer-a")

    assert store.load_candidates(run_id)[1].status.value == "duplicate"
    assert store.load_review_events(run_id)[0].action == "mark_duplicate"
    assert store.load_review_events(run_id)[0].reviewer == "reviewer-a"
    store.close()
