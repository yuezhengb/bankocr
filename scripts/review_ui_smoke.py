"""Run a headless smoke test for the optional PySide6 review window."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from bankocr.domain.run_manifest import RunManifest
from bankocr.gui.app import run_persisted_review
from bankocr.parser.models import FieldValue, TransactionCandidate
from bankocr.storage.project_store import ProjectStore
from bankocr.validation.engine import ValidationReport


def main() -> int:
    candidate = TransactionCandidate(
        page_index=0,
        row_index=0,
        parser_id="smoke:v1",
        fields={
            "transaction_date": FieldValue("2026-08-01", "2026-08-01"),
            "transaction_amount": FieldValue("1.00", "1.00"),
            "balance": FieldValue("1.00", "1.00"),
        },
    )
    with TemporaryDirectory() as directory:
        with ProjectStore(Path(directory) / "project.sqlite3") as store:
            project_id = store.create_project("ui-smoke", "statement.pdf")
            run_id = store.create_run(project_id, _manifest())
            store.save_candidates(run_id, (candidate,))
            store.save_validation_report(
                run_id,
                0,
                ValidationReport(checked_rows=1, issues=(), final_balances=()),
            )
            store.save_page_state(run_id, 0, "needs_review")
            store.set_run_status(run_id, "needs_review")

            app = QApplication.instance() or QApplication([])

            def accept_save_and_close() -> None:
                for widget in app.topLevelWidgets():
                    if hasattr(widget, "_accept_selected"):
                        widget.table.selectRow(0)
                        widget._accept_selected()
                        widget._save()
                        widget.close()
                app.quit()

            QTimer.singleShot(100, accept_save_and_close)
            exit_code = run_persisted_review(store, run_id)
            if exit_code != 0:
                raise SystemExit(f"review UI exited with code {exit_code}")
            if store.get_run_status(run_id) != "completed":
                raise SystemExit("review UI did not persist a completed run")
            if len(store.load_review_events(run_id)) != 1:
                raise SystemExit("review UI did not persist a review event")
            if store.load_candidates(run_id)[0].status.value != "accepted":
                raise SystemExit("review UI did not persist the accepted status")
    print("review_ui_smoke=ok")
    return 0


def _manifest() -> RunManifest:
    return RunManifest(
        app_version="0.1.0",
        project_schema_version="1",
        ocr_engine="smoke",
        ocr_model_id="smoke",
        model_sha256="a" * 64,
        execution_provider="cpu",
        preprocess_profile="smoke",
        parser_version="smoke",
        template_version="smoke",
        validation_rules_version="smoke",
        exporter_version="smoke",
    )


if __name__ == "__main__":
    raise SystemExit(main())
