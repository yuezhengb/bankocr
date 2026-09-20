import os
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace

import pytest
import pymupdf

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PySide6 = pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QWidget

import bankocr.gui.main_window as main_window
from bankocr.domain.run_manifest import RunManifest
from bankocr.gui.main_window import build_main_window
from bankocr.parser.models import FieldValue, TransactionCandidate
from bankocr.task.document_queue import PdfTask, PdfTaskExecutor, PdfTaskQueue


def _manifest() -> RunManifest:
    return RunManifest(
        app_version="test",
        project_schema_version="4",
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


class _Service:
    def start(self, project_id, manifest, source, *, dpi, checkpoint=None):
        if checkpoint is not None:
            checkpoint()
        return 1, {"pages": (0,)}


class _ArtifactExecutor:
    def __init__(self, artifacts: dict[str, str], store=None) -> None:
        self.artifacts = artifacts
        self.service = SimpleNamespace(store=store) if store is not None else None

    def execute(self, task, control):
        control.checkpoint()
        return {
            "run_id": 1,
            "result": {"pages": (0,)},
            "artifacts": self.artifacts,
        }


class _ReviewStore:
    def __init__(self) -> None:
        self.loaded_candidates: list[int] = []
        self.loaded_blocks: list[int] = []

    def load_candidates(self, run_id: int):
        self.loaded_candidates.append(run_id)
        return ()

    def load_ocr_blocks(self, run_id: int):
        self.loaded_blocks.append(run_id)
        return {}

    def page_states(self, _run_id: int):
        return ()


def test_main_window_adds_and_runs_pdf_queue_without_ocr_controls(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "statement.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(source)
    document.close()
    queue = PdfTaskQueue(PdfTaskExecutor(_Service()))
    window = build_main_window(
        queue,
        lambda path: PdfTask(path, 1, _manifest()),
    )

    window._add_files((source,))
    window._run_async()
    deadline = time.monotonic() + 5
    while window._thread is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)

    assert window.table.rowCount() == 1
    assert window.table.item(0, 1).text() == "已完成"
    assert window._thread is None
    assert not hasattr(window, "score_threshold")
    window.close()


def test_main_window_exposes_completed_outputs_and_result_actions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    QApplication.instance() or QApplication([])
    source = tmp_path / "statement.pdf"
    source.touch()
    output_dir = tmp_path / "输出" / "statement-result"
    output_dir.mkdir(parents=True)
    excel = output_dir / "statement.xlsx"
    pdf_layout_excel = output_dir / "statement.pdf-layout.xlsx"
    searchable_pdf = output_dir / "statement.searchable.pdf"
    comparison_pdf = output_dir / "statement.comparison.pdf"
    excel.touch()
    pdf_layout_excel.touch()
    searchable_pdf.touch()
    comparison_pdf.touch()
    review_store = _ReviewStore()
    queue = PdfTaskQueue(
        _ArtifactExecutor(
            {
                "excel": str(excel),
                "pdf_layout_excel": str(pdf_layout_excel),
                "searchable_pdf": str(searchable_pdf),
                "comparison_pdf": str(comparison_pdf),
            },
            review_store,
        )
    )
    opened: list[Path] = []
    open_succeeds = [True]

    def capture_open_url(url) -> bool:
        opened.append(Path(url.toLocalFile()))
        return open_succeeds[0]

    def forbid_subprocess(*_args, **_kwargs):
        raise AssertionError("GUI result actions must not invoke subprocess")

    monkeypatch.setattr(main_window, "_desktop_open_url", capture_open_url)
    monkeypatch.setattr(subprocess, "run", forbid_subprocess)
    monkeypatch.setattr(subprocess, "Popen", forbid_subprocess)
    window = build_main_window(
        queue,
        lambda path: PdfTask(path, 1, _manifest(), output_dir=output_dir),
        output_root=tmp_path / "输出",
    )

    assert window.add_button.text() == "选择 PDF"
    assert window.start_button.text() == "开始处理"
    assert window.output_folder_button.text() == "打开输出文件夹"
    assert window.excel_button.text() == "打开 Excel"
    assert window.pdf_layout_excel_button.text() == "打开 PDF 原样 Excel"
    assert window.searchable_pdf_button.text() == "打开可搜索 PDF"
    assert window.comparison_pdf_button.text() == "打开核对版 PDF"
    assert window.review_button.text() == "开始人工复核"
    assert window.instruction_label.text() == (
        "1. 选择或拖入 PDF  2. 点击开始处理  "
        "3. 完成后打开 Excel；要对照原排版时打开 PDF 原样 Excel；"
        "如果提示待复核，再点人工复核"
    )
    assert not window.output_folder_button.isEnabled()

    window._add_files((source,))
    window.table.selectRow(0)
    window._refresh_rows()

    assert not window.output_folder_button.isEnabled()
    assert not window.excel_button.isEnabled()
    assert not window.pdf_layout_excel_button.isEnabled()
    assert not window.searchable_pdf_button.isEnabled()
    assert not window.comparison_pdf_button.isEnabled()
    assert not window.review_button.isEnabled()

    queue.run_next()
    window._refresh_rows()

    assert window.table.item(0, 1).text() == "已完成"
    assert window._selected_output_dir() == output_dir
    assert window._selected_artifact_path("excel") == excel
    assert window._selected_artifact_path("pdf_layout_excel") == pdf_layout_excel
    assert window._selected_artifact_path("searchable_pdf") == searchable_pdf
    assert window._selected_artifact_path("comparison_pdf") == comparison_pdf
    assert window.output_folder_button.isEnabled()
    assert window.excel_button.isEnabled()
    assert window.pdf_layout_excel_button.isEnabled()
    assert window.searchable_pdf_button.isEnabled()
    assert window.comparison_pdf_button.isEnabled()
    assert window.review_button.isEnabled()
    window._open_output_folder()
    window._open_artifact("excel")
    window._open_artifact("pdf_layout_excel")
    window._open_artifact("searchable_pdf")
    window._open_artifact("comparison_pdf")

    assert opened == [output_dir, excel, pdf_layout_excel, searchable_pdf, comparison_pdf]

    open_succeeds[0] = False
    window._open_artifact("excel")
    assert window.status_label.text() == "无法打开 Excel，请检查文件是否仍存在"

    queue.restart(window._selected_task_id())
    window._refresh_rows()
    opened.clear()
    window._open_output_folder()
    assert opened == []
    assert window.status_label.text() == "请先选择已完成且有可用输出的任务"
    window.close()


def test_main_window_opens_persisted_review_without_output_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    QApplication.instance() or QApplication([])
    source = tmp_path / "statement.pdf"
    source.touch()
    review_store = _ReviewStore()
    queue = PdfTaskQueue(_ArtifactExecutor({}, review_store))
    window = build_main_window(queue, lambda path: PdfTask(path, 1, _manifest()))
    calls: dict[str, object] = {}
    review_window = QWidget()

    def fake_build_review_window(candidates, **kwargs):
        calls["candidates"] = candidates
        calls.update(kwargs)
        return review_window

    import bankocr.gui.app as review_app

    monkeypatch.setattr(review_app, "build_review_window", fake_build_review_window)
    window._add_files((source,))
    window.table.selectRow(0)
    queue.run_next()
    window._refresh_rows()

    assert window.review_button.isEnabled()
    assert not window.output_folder_button.isEnabled()
    window._open_review()

    assert review_store.loaded_candidates == [1]
    assert review_store.loaded_blocks == [1]
    assert calls["candidates"] == ()
    assert calls["source_pdf"] == source
    assert calls["blocks_by_page"] == {}
    assert review_window in window._review_windows
    review_window.close()
    window.close()


def test_main_window_disables_review_without_page_state_backend(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    source = tmp_path / "statement.pdf"
    source.touch()
    incomplete_store = SimpleNamespace(
        load_candidates=lambda _run_id: (),
        load_ocr_blocks=lambda _run_id: {},
    )
    queue = PdfTaskQueue(_ArtifactExecutor({}, incomplete_store))
    window = build_main_window(queue, lambda path: PdfTask(path, 1, _manifest()))

    window._add_files((source,))
    window.table.selectRow(0)
    queue.run_next()
    window._refresh_rows()

    assert not window.review_button.isEnabled()
    window.close()


class _BlockingExecutor:
    def __init__(self, store, release_event, entered_second_event) -> None:
        self.service = SimpleNamespace(store=store)
        self.release_event = release_event
        self.entered_second_event = entered_second_event
        self.calls = 0

    def execute(self, task, control):
        self.calls += 1
        if self.calls == 2:
            self.entered_second_event.set()
            while not self.release_event.is_set():
                control.checkpoint()
                time.sleep(0.01)
        return {"run_id": self.calls, "result": {"pages": (0,)}, "artifacts": {}}


class _ReviewRefreshExecutor:
    def __init__(self, store, initial_artifacts, refreshed_artifacts) -> None:
        self.service = SimpleNamespace(store=store)
        self.initial_artifacts = initial_artifacts
        self.refreshed_artifacts = refreshed_artifacts
        self.exported: list[tuple[PdfTask, int]] = []

    def execute(self, task, control):
        return {
            "run_id": 1,
            "result": {"needs_review_count": 1},
            "artifacts": dict(self.initial_artifacts),
        }

    def export_existing(self, payload, run_id):
        self.exported.append((payload, run_id))
        return dict(self.refreshed_artifacts)


class _StatefulReviewStore(_ReviewStore):
    def __init__(self) -> None:
        super().__init__()
        self.saved = False

    def page_states(self, _run_id: int):
        if self.saved:
            return ((0, "completed"),)
        return ((0, "needs_review"),)


class _FailingExecutor:
    def __init__(self, error: Exception) -> None:
        self.service = SimpleNamespace(store=None)
        self.error = error

    def execute(self, task, control):
        raise self.error


def _wait_for_async_window(window, app, timeout=5.0):
    deadline = time.monotonic() + timeout
    while window._thread is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def test_main_window_blocks_review_and_restart_actions_while_queue_runs(tmp_path: Path) -> None:
    import threading

    app = QApplication.instance() or QApplication([])
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    first.touch()
    second.touch()
    review_store = _ReviewStore()
    release = threading.Event()
    entered_second = threading.Event()
    queue = PdfTaskQueue(_BlockingExecutor(review_store, release, entered_second))
    window = build_main_window(queue, lambda path: PdfTask(path, 1, _manifest()))

    window._add_files((first, second))
    window.table.selectRow(0)
    window._run_async()
    deadline = time.monotonic() + 5
    while not entered_second.is_set() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    window._refresh_rows()

    assert window._queue_is_running()
    assert not window.review_button.isEnabled()
    assert not window.output_folder_button.isEnabled()
    window._open_review()
    assert review_store.loaded_candidates == []
    assert "\u961f\u5217" in window.status_label.text()
    window._restart_selected()
    assert queue.manager.get(window._task_ids[0]).status.value == "completed"

    release.set()
    _wait_for_async_window(window, app)
    assert window._thread is None
    window.close()


def test_main_window_refuses_start_while_review_window_is_open(tmp_path: Path, monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    source = tmp_path / "statement.pdf"
    source.touch()
    review_store = _ReviewStore()
    queue = PdfTaskQueue(_ArtifactExecutor({}, review_store))
    review_window = QWidget()

    import bankocr.gui.app as review_app

    monkeypatch.setattr(review_app, "build_review_window", lambda *_args, **_kwargs: review_window)
    window = build_main_window(queue, lambda path: PdfTask(path, 1, _manifest()))
    window._add_files((source,))
    window.table.selectRow(0)
    queue.run_next()
    window._refresh_rows()
    window._open_review()

    window._run_async()

    assert review_window in window._review_windows
    assert window._thread is None
    assert "\u590d\u6838" in window.status_label.text()
    review_window.close()
    window.close()


def test_main_window_refreshes_task_result_after_review_save(tmp_path: Path, monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    source = tmp_path / "statement.pdf"
    source.touch()
    old_excel = tmp_path / "old.xlsx"
    new_excel = tmp_path / "new.xlsx"
    old_excel.touch()
    new_excel.touch()
    store = _StatefulReviewStore()
    executor = _ReviewRefreshExecutor(
        store,
        {"excel": str(old_excel)},
        {"excel": str(new_excel)},
    )
    queue = PdfTaskQueue(executor)
    callbacks: dict[str, object] = {}
    review_window = QWidget()

    class FakeReviewService:
        def __init__(self, review_store) -> None:
            assert review_store is store

        def save(self, run_id, reviewed) -> None:
            assert run_id == 1
            store.saved = True

        def save_session(self, run_id, session) -> None:
            raise AssertionError("save_session should not be used")

    def fake_build_review_window(candidates, **kwargs):
        callbacks.update(kwargs)
        return review_window

    import bankocr.gui.app as review_app
    import bankocr.pipeline.review_service as review_service_module

    monkeypatch.setattr(review_app, "build_review_window", fake_build_review_window)
    monkeypatch.setattr(review_service_module, "ReviewService", FakeReviewService)
    window = build_main_window(queue, lambda path: PdfTask(path, 1, _manifest()))
    window._add_files((source,))
    window.table.selectRow(0)
    queue.run_next()
    window._refresh_rows()

    assert window.table.item(0, 3).text() == "1 \u9879\u5f85\u590d\u6838"
    window._open_review()
    callbacks["on_save"](())

    snapshot = queue.manager.get(window._task_ids[0])
    assert executor.exported == [(snapshot.task.payload, 1)]
    assert snapshot.result["artifacts"] == {"excel": str(new_excel)}
    assert snapshot.result["needs_review_count"] == 0
    assert window.table.item(0, 3).text() == ""
    review_window.close()
    window.close()


def test_main_window_logs_task_errors_and_shows_chinese_summary(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "statement.pdf"
    source.touch()
    log_root = tmp_path / "logs"
    queue = PdfTaskQueue(_FailingExecutor(FileNotFoundError("pdf vanished")))
    window = build_main_window(
        queue,
        lambda path: PdfTask(path, 1, _manifest(), output_dir=tmp_path / "out"),
        log_root=log_root,
    )
    task_id = queue.submit(PdfTask(source, 1, _manifest(), output_dir=tmp_path / "out"))
    window._task_ids.append(task_id)
    window.table.selectRow(0)

    window._run_async()
    _wait_for_async_window(window, app)

    hint = window.table.item(0, 3).text()
    assert "\u65e0\u6cd5\u8bfb\u53d6\u6587\u4ef6" in hint
    assert "statement.pdf" in hint
    assert "pdf vanished" not in hint
    logs = list(log_root.glob("*.log"))
    assert logs
    content = logs[0].read_text(encoding="utf-8")
    assert "FileNotFoundError" in content
    assert "statement.pdf" in content
    assert "Traceback" in content
    window.close()


def test_main_window_enables_retry_for_failed_task(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    source = tmp_path / "failed.pdf"
    source.touch()
    queue = PdfTaskQueue(_FailingExecutor(RuntimeError("boom")))
    window = build_main_window(queue, lambda path: PdfTask(path, 1, _manifest()))

    window._add_files((source,))
    window.table.selectRow(0)
    task_id = window._task_ids[0]
    snapshot = queue.run_next()
    assert snapshot is not None and snapshot.status.value == "failed"

    window._refresh_rows()

    assert window.restart_button.isEnabled()
    window._restart_selected()
    assert queue.manager.get(task_id).status.value == "queued"
    window.close()


def test_main_window_enables_retry_for_cancelled_task(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    source = tmp_path / "cancelled.pdf"
    source.touch()
    queue = PdfTaskQueue(_ArtifactExecutor({}))
    window = build_main_window(queue, lambda path: PdfTask(path, 1, _manifest()))

    window._add_files((source,))
    window.table.selectRow(0)
    task_id = window._task_ids[0]
    snapshot = queue.cancel(task_id)
    assert snapshot.status.value == "cancelled"

    window._refresh_rows()

    assert window.restart_button.isEnabled()
    window._restart_selected()
    assert queue.manager.get(task_id).status.value == "queued"
    window.close()
