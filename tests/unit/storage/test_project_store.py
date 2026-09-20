from pathlib import Path
from decimal import Decimal

from bankocr.domain.coordinates import Point
from bankocr.domain.review import ReviewOperation
from bankocr.domain.run_manifest import RunManifest
from bankocr.domain.text_block import SourceType, TextBlock
from bankocr.ocr.result import OCRPageResult
from bankocr.parser.models import FieldValue, TransactionCandidate
from bankocr.storage.project_store import ProjectStore
from bankocr.validation.engine import (
    IssueSeverity,
    ValidationIssue,
    ValidationReport,
    ValidationRuleState,
)


def _manifest() -> RunManifest:
    return RunManifest(
        app_version="0.1.0",
        project_schema_version="1",
        ocr_engine="rapidocr",
        ocr_model_id="PP-OCRv6-small",
        model_sha256="a" * 64,
        execution_provider="CPUExecutionProvider",
        preprocess_profile="default-v1",
        parser_version="parser-v1",
        template_version="template-v1",
        validation_rules_version="rules-v1",
        exporter_version="export-v1",
    )


def _candidate() -> TransactionCandidate:
    return TransactionCandidate(
        page_index=0,
        row_index=1,
        parser_id="template:test:v1",
        fields={
            "amount": FieldValue(
                "1O.00",
                "10.00",
                secondary_text="10.00",
                confidence=0.72,
            )
        },
    )


def test_project_store_persists_run_state_and_resume_pages(tmp_path: Path) -> None:
    database = tmp_path / "project.sqlite3"
    store = ProjectStore(database)
    project_id = store.create_project("demo", "statement.pdf")
    run_id = store.create_run(project_id, _manifest())
    store.save_page_state(run_id, 0, "completed")
    store.save_page_state(run_id, 1, "pending")
    store.save_candidates(run_id, (_candidate(),))
    store.close()

    reopened = ProjectStore(database)
    assert reopened.resume_pages(run_id) == (1,)
    assert reopened.page_states(run_id) == ((0, "completed"), (1, "pending"))
    loaded = reopened.load_candidates(run_id)
    assert loaded[0].field("amount").raw_text == "1O.00"
    assert loaded[0].field("amount").suggested_text == "10.00"
    assert loaded[0].field("amount").secondary_text == "10.00"
    assert loaded[0].field("amount").final_text is None
    reopened.close()


def test_project_store_round_trips_run_manifest(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")
    run_id = store.create_run(project_id, _manifest())

    assert store.get_run_manifest(run_id) == _manifest()
    assert store.get_run_source_path(run_id) == Path("statement.pdf")
    assert store.schema_version() == 6
    store.close()


def test_project_store_rejects_unknown_page_status(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")
    run_id = store.create_run(project_id, _manifest())

    try:
        store.save_page_state(run_id, 0, "made-up")
    except ValueError as exc:
        assert "status" in str(exc)
    else:
        raise AssertionError("expected invalid page state to fail")
    finally:
        store.close()


def test_project_store_seeds_only_missing_page_states(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")
    run_id = store.create_run(project_id, _manifest())
    store.save_page_state(run_id, 0, "completed")

    store.seed_page_states(run_id, (0, 1, 2))

    assert store.page_statuses(run_id) == ("completed", "pending", "pending")
    assert store.resume_pages(run_id) == (1, 2)
    store.close()


def test_project_store_persists_validation_reports_with_decimal_balances(tmp_path: Path) -> None:
    from decimal import Decimal

    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")
    run_id = store.create_run(project_id, _manifest())
    report = ValidationReport(
        checked_rows=2,
        issues=(
            ValidationIssue(
                code="balance_mismatch",
                message="expected 2.00, got 3.00",
                severity=IssueSeverity.CRITICAL,
                row_index=1,
                field_name="balance",
            ),
        ),
        final_balances=(Decimal("1.00"), Decimal("3.00")),
    )

    store.save_validation_report(run_id, 0, report)
    store.close()

    reopened = ProjectStore(tmp_path / "project.sqlite3")
    loaded = reopened.load_validation_reports(run_id)

    assert loaded[0].checked_rows == 2
    assert loaded[0].final_balances == (Decimal("1.00"), Decimal("3.00"))
    assert loaded[0].issues[0].severity is IssueSeverity.CRITICAL
    assert loaded[0].issues[0].field_name == "balance"
    reopened.close()


def test_project_store_persists_ocr_blocks_for_recovered_exports(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")
    run_id = store.create_run(project_id, _manifest())
    block = TextBlock(
        text="交易摘要",
        raw_text="交易摘要",
        polygon=(Point(1, 2), Point(20, 2), Point(20, 10), Point(1, 10)),
        confidence=0.91,
        source_type=SourceType.OCR,
        page_index=0,
        engine_id="test",
    )

    store.save_ocr_result(run_id, OCRPageResult(0, (block,), "test"))
    store.close()

    reopened = ProjectStore(tmp_path / "project.sqlite3")
    loaded = reopened.load_ocr_blocks(run_id)

    assert loaded[0][0] == block
    reopened.close()


def test_project_store_save_review_completes_only_clean_review_pages(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")
    run_id = store.create_run(project_id, _manifest())
    candidate = _candidate()
    store.save_candidates(run_id, (candidate,))
    store.save_validation_report(
        run_id,
        0,
        ValidationReport(checked_rows=1, issues=(), final_balances=()),
    )
    store.save_page_state(run_id, 0, "needs_review")
    store.set_run_status(run_id, "needs_review")

    store.save_review(run_id, (candidate.accept(),))

    assert store.page_statuses(run_id) == ("completed",)
    assert store.get_run_status(run_id) == "completed"
    assert store.load_candidates(run_id)[0].status.value == "accepted"
    events = store.load_review_events(run_id)
    assert len(events) == 1
    assert events[0].action == "candidate_updated"
    assert "final_text" in events[0].after_json
    store.close()


def test_project_store_keeps_validation_issue_pages_in_review_after_edit(tmp_path: Path) -> None:
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
                    code="balance_mismatch",
                    message="manual review required",
                    severity=IssueSeverity.CRITICAL,
                    row_index=1,
                ),
            ),
            final_balances=(),
        ),
    )
    store.save_page_state(run_id, 0, "needs_review")
    store.set_run_status(run_id, "needs_review")

    store.save_review(run_id, (candidate.accept(),))

    assert store.page_statuses(run_id) == ("needs_review",)
    assert store.get_run_status(run_id) == "needs_review"
    store.close()


def test_project_store_does_not_keep_not_applicable_rule_in_review(tmp_path: Path) -> None:
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
                    code="page_total_not_available",
                    message="not applicable for this statement",
                    severity=IssueSeverity.ERROR,
                    row_index=1,
                    rule_state=ValidationRuleState.NOT_APPLICABLE,
                ),
            ),
            final_balances=(),
        ),
    )
    store.save_page_state(run_id, 0, "needs_review")
    store.set_run_status(run_id, "needs_review")

    store.save_review(run_id, (candidate.accept(),))

    assert store.page_statuses(run_id) == ("completed",)
    assert store.get_run_status(run_id) == "completed"
    store.close()


def test_project_store_rejects_review_candidates_not_owned_by_the_run(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")
    run_id = store.create_run(project_id, _manifest())

    try:
        store.save_review(run_id, (_candidate(),))
    except ValueError as exc:
        assert "does not belong" in str(exc)
    else:
        raise AssertionError("expected foreign review candidate to fail")
    store.close()


def test_project_store_replaces_all_page_artifacts_on_retry(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")
    run_id = store.create_run(project_id, _manifest())
    block = TextBlock(
        text="old",
        raw_text="old",
        polygon=(Point(1, 2), Point(20, 2), Point(20, 10), Point(1, 10)),
        confidence=0.91,
        source_type=SourceType.OCR,
        page_index=0,
        engine_id="test",
    )
    first_report = ValidationReport(
        checked_rows=1,
        issues=(),
        final_balances=(Decimal("1.00"),),
    )
    store.save_page_result(
        run_id,
        0,
        (_candidate(),),
        OCRPageResult(0, (block,), "test"),
        first_report,
        "needs_review",
    )
    replacement = TransactionCandidate(
        page_index=0,
        row_index=2,
        parser_id="template:test:v2",
        fields={"amount": FieldValue("2.00", "2.00")},
    )

    store.save_page_result(run_id, 0, (replacement,), None, None, "failed", "retry failed")

    assert store.load_candidates(run_id) == (replacement,)
    assert store.load_ocr_blocks(run_id) == {}
    assert store.load_validation_reports(run_id) == {}
    assert store.page_errors(run_id) == {0: "retry failed"}
    store.close()


def test_project_store_migrates_schema_v3_validation_reports(tmp_path: Path) -> None:
    import sqlite3

    database = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT NOT NULL, source_path TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE runs (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, status TEXT NOT NULL, manifest_json TEXT NOT NULL, source_sha256 TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE pages (run_id INTEGER NOT NULL, page_index INTEGER NOT NULL, status TEXT NOT NULL, error TEXT, PRIMARY KEY(run_id, page_index));
        CREATE TABLE candidates (run_id INTEGER NOT NULL, page_index INTEGER NOT NULL, row_index INTEGER NOT NULL, parser_id TEXT NOT NULL, status TEXT NOT NULL, fields_json TEXT NOT NULL, PRIMARY KEY(run_id, page_index, row_index));
        CREATE TABLE validation_reports (run_id INTEGER NOT NULL, page_index INTEGER NOT NULL, checked_rows INTEGER NOT NULL, issues_json TEXT NOT NULL, balances_json TEXT NOT NULL, PRIMARY KEY(run_id, page_index));
        CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO schema_meta(key, value) VALUES ('schema_version', '3');
        """
    )
    connection.commit()
    connection.close()

    store = ProjectStore(database)
    columns = {
        row[1]
        for row in store.connection.execute("PRAGMA table_info(validation_reports)").fetchall()
    }
    assert store.schema_version() == 6
    assert {"status", "risk_score", "reasons_json"} <= columns
    store.close()


def test_project_store_round_trips_structure_review_and_audit(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")
    run_id = store.create_run(project_id, _manifest())
    first = _candidate()
    second = TransactionCandidate(
        page_index=0,
        row_index=2,
        parser_id="template:test:v1",
        fields={"amount": FieldValue("2.00", "2.00")},
    )
    store.save_candidates(run_id, (first, second))
    store.save_page_state(run_id, 0, "needs_review")
    store.set_run_status(run_id, "needs_review")
    edited = first.accept()
    duplicate = second.mark_duplicate((0, 1))

    store.save_structure_review(
        run_id,
        (edited, duplicate),
        operations=(
            ReviewOperation(
                action="mark_duplicate",
                page_index=0,
                row_index=2,
                related_page_index=0,
                related_row_index=1,
            ),
        ),
        reviewer="reviewer-a",
    )

    loaded = store.load_candidates(run_id)
    assert loaded[0].status.value == "accepted"
    assert loaded[1].status.value == "duplicate"
    assert loaded[1].duplicate_of == (0, 1)
    events = store.load_review_events(run_id)
    assert len(events) == 1
    assert events[0].action == "mark_duplicate"
    assert '"duplicate_of"' in events[0].after_json
    assert events[0].reviewer == "reviewer-a"
    store.close()


def test_project_store_rejects_structure_snapshot_with_duplicate_identity(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")
    run_id = store.create_run(project_id, _manifest())
    original = _candidate()
    store.save_candidates(run_id, (original,))

    duplicate_identity = TransactionCandidate(
        page_index=original.page_index,
        row_index=original.row_index,
        parser_id="review:add",
        fields={"amount": FieldValue("2.00", "2.00")},
    )
    try:
        store.save_structure_review(
            run_id,
            (original, duplicate_identity),
            operations=(ReviewOperation(action="add", page_index=0, row_index=1),),
        )
    except ValueError as exc:
        assert "duplicate candidate identity" in str(exc)
    else:
        raise AssertionError("expected duplicate candidate identity to fail")
    assert store.load_candidates(run_id) == (original,)
    store.close()
