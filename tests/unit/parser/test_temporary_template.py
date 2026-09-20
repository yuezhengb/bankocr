from pathlib import Path

import pytest

from bankocr.domain.run_manifest import RunManifest
from bankocr.parser.temporary_template import TemporaryTemplateConfirmation
from bankocr.parser.templates import ColumnDefinition
from bankocr.storage.project_store import ProjectStore


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


def _confirmation(run_id: int) -> TemporaryTemplateConfirmation:
    return TemporaryTemplateConfirmation(
        run_id=run_id,
        source_page_index=1,
        header_tokens=("日期", "金额", "余额"),
        columns=(
            ColumnDefinition("accounting_date", 0.0, 0.25),
            ColumnDefinition("transaction_amount", 0.25, 0.65),
            ColumnDefinition("balance", 0.65, 1.0),
        ),
        required_fields=("accounting_date", "balance"),
        confirmed_by="reviewer-a",
    )


def test_temporary_template_confirmation_is_run_scoped() -> None:
    confirmation = _confirmation(12)

    record = confirmation.to_record()

    assert record.template.template_id == "temporary:run-12:page-1"
    assert record.template.version == "temporary-v1"
    assert record.template.row_strategy == "anchor_date"
    assert record.confirmed_by == "reviewer-a"


def test_temporary_template_rejects_overlapping_columns() -> None:
    with pytest.raises(ValueError, match="overlap"):
        TemporaryTemplateConfirmation(
            run_id=1,
            source_page_index=0,
            header_tokens=("date",),
            columns=(
                ColumnDefinition("date", 0.0, 0.6),
                ColumnDefinition("balance", 0.5, 1.0),
            ),
            required_fields=("date",),
        )


def test_temporary_template_record_rejects_cross_run_template_id() -> None:
    confirmation = _confirmation(12)
    with pytest.raises(ValueError, match="match its run"):
        from bankocr.parser.temporary_template import TemporaryTemplateRecord

        TemporaryTemplateRecord(
            run_id=13,
            source_page_index=confirmation.source_page_index,
            template=confirmation.to_record().template,
            confirmed_by="reviewer-a",
        )


def test_project_store_round_trips_temporary_template_per_run(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")
    first_run = store.create_run(project_id, _manifest())
    second_run = store.create_run(project_id, _manifest())
    confirmation = _confirmation(first_run)

    store.save_temporary_template(confirmation.to_record())

    loaded = store.load_temporary_template(first_run)
    assert loaded is not None
    assert loaded.template == confirmation.to_record().template
    assert loaded.source_page_index == 1
    assert loaded.confirmed_by == "reviewer-a"
    assert store.load_temporary_template(second_run) is None
    store.close()
