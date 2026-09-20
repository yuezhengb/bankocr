import json
from pathlib import Path

from bankocr.domain.run_manifest import RunManifest
from bankocr.template_cli import main
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


def test_template_cli_saves_mapping_and_requeues_review_pages(tmp_path: Path, capsys) -> None:
    database = tmp_path / "project.sqlite3"
    store = ProjectStore(database)
    project_id = store.create_project("demo", "statement.pdf")
    run_id = store.create_run(project_id, _manifest())
    store.save_page_state(run_id, 0, "needs_review", "confirm columns")
    store.close()

    assert main(
        [
            "--project-db",
            str(database),
            "--run-id",
            str(run_id),
            "--source-page",
            "0",
            "--headers",
            "date,amount,balance",
            "--columns",
            "accounting_date:0:0.3;transaction_amount:0.3:0.7;balance:0.7:1",
            "--required-fields",
            "accounting_date,balance",
            "--reviewer",
            "reviewer-a",
        ]
    ) == 0

    with ProjectStore(database) as reopened:
        record = reopened.load_temporary_template(run_id)
        assert record is not None
        assert record.template.template_id == f"temporary:run-{run_id}:page-0"
        assert reopened.page_states(run_id) == ((0, "pending"),)
    assert "temporary template saved" in capsys.readouterr().out
