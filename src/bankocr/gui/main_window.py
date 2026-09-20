"""Small PySide6 main window for the offline PDF queue."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from bankocr.gui.error_reporting import user_error_summary, write_error_log
from bankocr.task.document_queue import PdfTask, PdfTaskQueue


def _desktop_open_url(url) -> bool:
    """Open a local URL through Qt's desktop integration."""

    from PySide6.QtGui import QDesktopServices

    return QDesktopServices.openUrl(url)


def build_main_window(
    queue: PdfTaskQueue,
    task_factory: Callable[[Path], PdfTask],
    *,
    output_root: Path | None = None,
    log_root: Path | None = None,
):
    """Build a drag-and-drop window without exposing OCR implementation knobs."""

    try:
        from PySide6.QtCore import QObject, QThread, QTimer, QUrl, Qt, Signal, Slot
        from PySide6.QtWidgets import (
            QFileDialog,
            QHBoxLayout,
            QLabel,
            QMainWindow,
            QPushButton,
            QTableWidget,
            QTableWidgetItem,
            QVBoxLayout,
            QWidget,
        )
    except ModuleNotFoundError as exc:
        raise RuntimeError("GUI requires the optional PySide6 dependency") from exc

    class QueueWorker(QObject):
        finished = Signal(object)
        failed = Signal(object)

        def __init__(self, task_queue: PdfTaskQueue) -> None:
            super().__init__()
            self.task_queue = task_queue

        @Slot()
        def run(self) -> None:
            try:
                self.finished.emit(self.task_queue.run_all())
            except Exception as exc:
                self.failed.emit(exc)

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setAcceptDrops(True)
            self.setWindowTitle("BankOCR 离线流水处理")
            self.queue = queue
            self.task_factory = task_factory
            self.output_root = output_root
            self.log_root = log_root
            self._logged_errors: set[tuple[str, int]] = set()
            self._task_ids: list[str] = []
            self.instruction_label = QLabel(
                "1. 选择或拖入 PDF  2. 点击开始处理  "
                "3. 完成后打开 Excel；要对照原排版时打开 PDF 原样 Excel；"
                "如果提示待复核，再点人工复核"
            )
            self.instruction_label.setWordWrap(True)
            self.output_root_label = QLabel(_output_root_text(output_root))
            self.output_root_label.setWordWrap(True)
            self.drop_label = QLabel("将 PDF 拖到这里，或点击“选择 PDF”")
            self.drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.drop_label.setMinimumHeight(72)
            self.status_label = QLabel("请先添加 PDF 文件")
            self.table = QTableWidget(0, 4)
            self.table.setHorizontalHeaderLabels(("文件", "处理状态", "页数", "提示"))
            self.add_button = QPushButton("选择 PDF")
            self.start_button = QPushButton("开始处理")
            self.output_folder_button = QPushButton("打开输出文件夹")
            self.excel_button = QPushButton("打开 Excel")
            self.pdf_layout_excel_button = QPushButton("打开 PDF 原样 Excel")
            self.searchable_pdf_button = QPushButton("打开可搜索 PDF")
            self.comparison_pdf_button = QPushButton("打开核对版 PDF")
            self.review_button = QPushButton("开始人工复核")
            self.pause_button = QPushButton("暂停")
            self.resume_button = QPushButton("继续")
            self.cancel_button = QPushButton("取消")
            self.restart_button = QPushButton("重试")
            self.add_button.clicked.connect(self._choose_files)
            self.start_button.clicked.connect(self._run_async)
            self.output_folder_button.clicked.connect(self._open_output_folder)
            self.excel_button.clicked.connect(lambda: self._open_artifact("excel"))
            self.pdf_layout_excel_button.clicked.connect(
                lambda: self._open_artifact("pdf_layout_excel")
            )
            self.searchable_pdf_button.clicked.connect(
                lambda: self._open_artifact("searchable_pdf")
            )
            self.comparison_pdf_button.clicked.connect(
                lambda: self._open_artifact("comparison_pdf")
            )
            self.pause_button.clicked.connect(self._pause_selected)
            self.resume_button.clicked.connect(self._resume_selected)
            self.cancel_button.clicked.connect(self._cancel_selected)
            self.restart_button.clicked.connect(self._restart_selected)
            self.review_button.clicked.connect(self._open_review)
            self.table.itemSelectionChanged.connect(self._update_result_actions)
            primary_controls = QHBoxLayout()
            for button in (self.add_button, self.start_button):
                primary_controls.addWidget(button)
            result_controls = QVBoxLayout()
            result_row_one = QHBoxLayout()
            for button in (
                self.output_folder_button,
                self.excel_button,
                self.pdf_layout_excel_button,
            ):
                result_row_one.addWidget(button)
            result_row_two = QHBoxLayout()
            for button in (
                self.searchable_pdf_button,
                self.comparison_pdf_button,
                self.review_button,
            ):
                result_row_two.addWidget(button)
            result_controls.addLayout(result_row_one)
            result_controls.addLayout(result_row_two)
            advanced_controls = QHBoxLayout()
            for button in (
                self.pause_button,
                self.resume_button,
                self.cancel_button,
                self.restart_button,
            ):
                advanced_controls.addWidget(button)
            central = QWidget()
            layout = QVBoxLayout(central)
            layout.addWidget(self.instruction_label)
            layout.addWidget(self.output_root_label)
            layout.addWidget(self.drop_label)
            layout.addLayout(primary_controls)
            layout.addWidget(self.table)
            layout.addLayout(result_controls)
            layout.addLayout(advanced_controls)
            layout.addWidget(self.status_label)
            self.setCentralWidget(central)
            self._thread = None
            self._worker = None
            self._refresh_timer = QTimer(self)
            self._refresh_timer.setInterval(250)
            self._refresh_timer.timeout.connect(self._refresh_rows)
            self._review_windows = []
            self._desktop_open_url = _desktop_open_url
            self._update_result_actions()

        def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt API
            if event.mimeData().hasUrls():
                event.acceptProposedAction()

        def dropEvent(self, event) -> None:  # noqa: N802 - Qt API
            self._add_files(
                Path(url.toLocalFile())
                for url in event.mimeData().urls()
                if url.toLocalFile().lower().endswith(".pdf")
            )
            event.acceptProposedAction()

        def _queue_is_running(self) -> bool:
            return self._thread is not None and self._thread.isRunning()

        def _has_open_review_window(self) -> bool:
            return bool(self._review_windows)

        def _queue_busy_message(self) -> str:
            return "\u961f\u5217\u6b63\u5728\u5904\u7406\uff0c\u8bf7\u5148\u7b49\u5f85\u5b8c\u6210\u6216\u53d6\u6d88\u5f53\u524d\u961f\u5217\u3002"

        def _review_open_message(self) -> str:
            return "\u8bf7\u5148\u5173\u95ed\u4eba\u5de5\u590d\u6838\u7a97\u53e3\uff0c\u518d\u5f00\u59cb\u5904\u7406\u961f\u5217\u3002"

        def _guard_store_action(self) -> bool:
            if self._queue_is_running():
                self.status_label.setText(self._queue_busy_message())
                return False
            return True

        def _choose_files(self) -> None:
            files, _ = QFileDialog.getOpenFileNames(self, "选择银行流水 PDF", "", "PDF (*.pdf)")
            self._add_files(Path(item) for item in files)

        def _add_files(self, paths) -> None:
            if self._queue_is_running():
                self.status_label.setText("任务运行中，请先完成或取消当前队列")
                return
            added = 0
            for path in paths:
                if not path.is_file() or path.suffix.casefold() != ".pdf":
                    continue
                task_id = self.queue.submit(self.task_factory(path))
                self._task_ids.append(task_id)
                added += 1
            if added:
                self._refresh_rows()
                self.status_label.setText(f"已加入 {added} 个 PDF")

        def _run_next(self) -> None:
            snapshot = self.queue.run_next()
            self._refresh_rows()
            if snapshot is not None:
                self.status_label.setText(f"处理完成：{snapshot.task_id}")

        def _run_async(self) -> None:
            if self._queue_is_running():
                return
            if self._has_open_review_window():
                self.status_label.setText(self._review_open_message())
                return
            self._thread = QThread(self)
            self._worker = QueueWorker(self.queue)
            self._worker.moveToThread(self._thread)
            self._thread.started.connect(self._worker.run)
            self._worker.finished.connect(self._async_finished)
            self._worker.failed.connect(self._async_failed)
            self._worker.finished.connect(self._thread.quit)
            self._worker.failed.connect(self._thread.quit)
            self._worker.finished.connect(self._worker.deleteLater)
            self._worker.failed.connect(self._worker.deleteLater)
            self._thread.finished.connect(self._thread_finished)
            self.add_button.setEnabled(False)
            self.start_button.setEnabled(False)
            self.status_label.setText("正在离线处理队列…")
            self._refresh_timer.start()
            self._thread.start()

        def _async_finished(self, snapshots) -> None:
            for snapshot in snapshots:
                self._log_snapshot_error_once(snapshot)
            self._refresh_rows()
            completed = sum(item.status.value == "completed" for item in snapshots)
            failed = sum(item.status.value in {"failed", "cancelled"} for item in snapshots)
            self.status_label.setText(f"\u961f\u5217\u5904\u7406\u5b8c\u6210\uff1a\u6210\u529f {completed}\uff0c\u672a\u5b8c\u6210 {failed}")

        def _async_failed(self, error) -> None:
            write_error_log(
                log_root=self.log_root,
                context="queue",
                error=error if isinstance(error, BaseException) else None,
                message=None if isinstance(error, BaseException) else str(error),
            )
            self._refresh_rows()
            self.status_label.setText(
                user_error_summary(error, log_root=self.log_root)
            )

        def _thread_finished(self) -> None:
            self._refresh_timer.stop()
            self.add_button.setEnabled(True)
            self.start_button.setEnabled(True)
            thread = self._thread
            self._thread = None
            self._worker = None
            if thread is not None:
                thread.deleteLater()
            self._update_result_actions()
        def _selected_task_id(self) -> str | None:
            row = self.table.currentRow()
            return self._task_ids[row] if 0 <= row < len(self._task_ids) else None

        def _selected_snapshot(self):
            task_id = self._selected_task_id()
            return None if task_id is None else self.queue.manager.get(task_id)

        def _selected_output_dir(self) -> Path | None:
            snapshot = self._selected_snapshot()
            payload = None if snapshot is None else snapshot.task.payload
            if not isinstance(payload, PdfTask) or payload.output_dir is None:
                return None
            return payload.output_dir

        def _selected_artifact_path(self, name: str) -> Path | None:
            snapshot = self._selected_snapshot()
            result = None if snapshot is None else snapshot.result
            if not isinstance(result, dict):
                return None
            artifacts = result.get("artifacts")
            if not isinstance(artifacts, dict):
                return None
            value = artifacts.get(name)
            if not isinstance(value, (str, Path)):
                return None
            path = Path(value)
            return path if path.is_file() else None

        def _selected_run_id(self) -> int | None:
            snapshot = self._selected_snapshot()
            result = None if snapshot is None else snapshot.result
            if not isinstance(result, dict):
                return None
            run_id = result.get("run_id")
            return run_id if isinstance(run_id, int) else None

        def _has_completed_result(self) -> bool:
            snapshot = self._selected_snapshot()
            return (
                snapshot is not None
                and snapshot.status.value == "completed"
                and isinstance(snapshot.result, dict)
            )

        def _review_store(self):
            service = getattr(self.queue.executor, "service", None)
            store = getattr(service, "store", None)
            if not callable(getattr(store, "load_candidates", None)):
                return None
            if not callable(getattr(store, "load_ocr_blocks", None)):
                return None
            if not callable(getattr(store, "page_states", None)):
                return None
            return store

        def _update_result_actions(self) -> None:
            snapshot = self._selected_snapshot()
            has_selection = snapshot is not None
            if self._queue_is_running():
                self.output_folder_button.setEnabled(False)
                self.excel_button.setEnabled(False)
                self.pdf_layout_excel_button.setEnabled(False)
                self.searchable_pdf_button.setEnabled(False)
                self.comparison_pdf_button.setEnabled(False)
                self.review_button.setEnabled(False)
                self.resume_button.setEnabled(False)
                self.restart_button.setEnabled(False)
                self.pause_button.setEnabled(has_selection)
                self.cancel_button.setEnabled(has_selection)
                return
            has_completed_result = self._has_completed_result()
            output_dir = self._selected_output_dir()
            has_output_dir = (
                has_completed_result and output_dir is not None and output_dir.is_dir()
            )
            self.output_folder_button.setEnabled(has_output_dir)
            self.excel_button.setEnabled(
                has_completed_result
                and self._selected_artifact_path("excel") is not None
            )
            self.pdf_layout_excel_button.setEnabled(
                has_completed_result
                and self._selected_artifact_path("pdf_layout_excel") is not None
            )
            self.searchable_pdf_button.setEnabled(
                has_completed_result
                and self._selected_artifact_path("searchable_pdf") is not None
            )
            self.comparison_pdf_button.setEnabled(
                has_completed_result
                and self._selected_artifact_path("comparison_pdf") is not None
            )
            self.review_button.setEnabled(
                has_completed_result
                and self._selected_run_id() is not None
                and self._review_store() is not None
            )
            self.pause_button.setEnabled(has_selection)
            self.resume_button.setEnabled(has_selection)
            self.cancel_button.setEnabled(has_selection)
            restartable = (
                snapshot is not None
                and snapshot.status.value in {"completed", "failed", "cancelled"}
            )
            self.restart_button.setEnabled(restartable)

        def _open_output_folder(self) -> None:
            if not self._guard_store_action():
                return
            output_dir = self._selected_output_dir()
            if (
                not self._has_completed_result()
                or output_dir is None
                or not output_dir.is_dir()
            ):
                self.status_label.setText("请先选择已完成且有可用输出的任务")
                return
            self._open_local_path(output_dir, "输出文件夹")

        def _open_artifact(self, name: str) -> None:
            if not self._guard_store_action():
                return
            path = self._selected_artifact_path(name)
            if not self._has_completed_result() or path is None:
                self.status_label.setText("请先选择已完成且有可用输出的任务")
                return
            labels = {
                "excel": "Excel",
                "pdf_layout_excel": "PDF 原样 Excel",
                "searchable_pdf": "可搜索 PDF",
                "comparison_pdf": "核对版 PDF",
            }
            self._open_local_path(path, labels.get(name, "结果文件"))

        def _open_local_path(self, path: Path, label: str) -> None:
            if not self._desktop_open_url(QUrl.fromLocalFile(str(path))):
                self.status_label.setText(f"无法打开 {label}，请检查文件是否仍存在")

        def _pause_selected(self) -> None:
            task_id = self._selected_task_id()
            if task_id:
                try:
                    self.queue.pause(task_id)
                    self.status_label.setText("已请求在当前页完成后暂停")
                except Exception as exc:
                    self.status_label.setText(user_error_summary(exc, log_root=self.log_root))
                self._refresh_rows()

        def _resume_selected(self) -> None:
            if not self._guard_store_action():
                return
            task_id = self._selected_task_id()
            if task_id:
                try:
                    self.queue.resume(task_id)
                    self.status_label.setText("任务已继续")
                except Exception as exc:
                    self.status_label.setText(user_error_summary(exc, log_root=self.log_root))
                self._refresh_rows()

        def _cancel_selected(self) -> None:
            task_id = self._selected_task_id()
            if task_id:
                try:
                    self.queue.cancel(task_id)
                    self.status_label.setText("已请求在当前页完成后取消")
                except Exception as exc:
                    self.status_label.setText(user_error_summary(exc, log_root=self.log_root))
                self._refresh_rows()

        def _restart_selected(self) -> None:
            if not self._guard_store_action():
                return
            task_id = self._selected_task_id()
            if task_id:
                try:
                    self.queue.restart(task_id)
                    self.status_label.setText("任务已重新加入队列")
                except Exception as exc:
                    self.status_label.setText(user_error_summary(exc, log_root=self.log_root))
                self._refresh_rows()

        def _open_review(self) -> None:
            if not self._guard_store_action():
                return
            snapshot = self._selected_snapshot()
            run_id = self._selected_run_id()
            store = self._review_store()
            if (
                not self._has_completed_result()
                or snapshot is None
                or run_id is None
                or store is None
            ):
                self.status_label.setText("\u8be5\u4efb\u52a1\u6682\u65e0\u53ef\u7528\u7684\u4eba\u5de5\u590d\u6838\u7ed3\u679c")
                return
            from bankocr.gui.app import build_review_window
            from bankocr.pipeline.review_service import ReviewService

            task_id = snapshot.task_id
            payload = snapshot.task.payload

            def refresh_task_result(artifacts: dict[str, str]) -> None:
                current = self.queue.manager.get(task_id).result
                base = dict(current) if isinstance(current, dict) else {}
                base["artifacts"] = dict(artifacts)
                base["needs_review_count"] = _needs_review_count_from_store(store, run_id)
                self.queue.update_result(task_id, base)

            def save(reviewed) -> None:
                if not self._guard_store_action():
                    return
                try:
                    ReviewService(store).save(run_id, reviewed)
                    artifacts = self.queue.executor.export_existing(payload, run_id)
                    refresh_task_result(artifacts)
                except Exception as exc:
                    self._log_task_error(task_id, exc)
                    self.status_label.setText(
                        user_error_summary(
                            exc,
                            source=getattr(payload, "source", None),
                            output_dir=getattr(payload, "output_dir", None),
                            log_root=self.log_root,
                        )
                    )
                    return
                self.status_label.setText("\u590d\u6838\u5df2\u4fdd\u5b58\uff0c\u5bfc\u51fa\u6587\u4ef6\u5df2\u66f4\u65b0")
                self._refresh_rows()

            def save_session(session) -> None:
                if not self._guard_store_action():
                    return
                try:
                    ReviewService(store).save_session(run_id, session)
                    artifacts = self.queue.executor.export_existing(payload, run_id)
                    refresh_task_result(artifacts)
                except Exception as exc:
                    self._log_task_error(task_id, exc)
                    self.status_label.setText(
                        user_error_summary(
                            exc,
                            source=getattr(payload, "source", None),
                            output_dir=getattr(payload, "output_dir", None),
                            log_root=self.log_root,
                        )
                    )
                    return
                self.status_label.setText("\u590d\u6838\u5df2\u4fdd\u5b58\uff0c\u5bfc\u51fa\u6587\u4ef6\u5df2\u66f4\u65b0")
                self._refresh_rows()

            def save_temporary_template(confirmation) -> None:
                if not self._guard_store_action():
                    return
                try:
                    store.save_temporary_template(confirmation.to_record())
                    store.requeue_review_pages(run_id)
                    self.queue.restart(task_id)
                    message = "Temporary Template \u5df2\u4fdd\u5b58\uff1b\u4efb\u52a1\u5df2\u91cd\u65b0\u6392\u961f\uff0c\u70b9\u51fb\u201c\u5f00\u59cb\u201d\u91cd\u8dd1"
                except Exception as exc:
                    self._log_task_error(task_id, exc)
                    message = user_error_summary(
                        exc,
                        source=getattr(payload, "source", None),
                        output_dir=getattr(payload, "output_dir", None),
                        log_root=self.log_root,
                    )
                self.status_label.setText(message)
                self._refresh_rows()

            review = build_review_window(
                store.load_candidates(run_id),
                on_save=save,
                on_save_session=save_session,
                on_confirm_temporary_template=save_temporary_template,
                temporary_template_run_id=run_id,
                temporary_template_page=next(
                    (
                        page_index
                        for page_index, status in store.page_states(run_id)
                        if status == "needs_review"
                    ),
                    None,
                ),
                source_pdf=payload.source,
                blocks_by_page=store.load_ocr_blocks(run_id),
            )
            review.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            self._review_windows.append(review)
            review.destroyed.connect(
                lambda *_: self._review_windows.remove(review)
                if review in self._review_windows
                else None
            )
            review.show()

        def _log_task_error(self, task_id: str, error: BaseException) -> None:
            snapshot = self.queue.manager.get(task_id)
            payload = snapshot.task.payload
            write_error_log(
                log_root=self.log_root,
                context="task",
                error=error,
                task_id=task_id,
                source=getattr(payload, "source", None),
                output_dir=getattr(payload, "output_dir", None),
            )

        def _log_snapshot_error_once(self, snapshot) -> None:
            error = getattr(snapshot, "error", None)
            if error is None:
                return
            key = (snapshot.task_id, snapshot.attempt_number)
            if key in self._logged_errors:
                return
            self._logged_errors.add(key)
            payload = snapshot.task.payload
            write_error_log(
                log_root=self.log_root,
                context="task",
                error=error,
                task_id=snapshot.task_id,
                source=getattr(payload, "source", None),
                output_dir=getattr(payload, "output_dir", None),
            )

        def _refresh_rows(self) -> None:
            self.table.setRowCount(len(self._task_ids))
            for row, task_id in enumerate(self._task_ids):
                snapshot = self.queue.manager.get(task_id)
                self._log_snapshot_error_once(snapshot)
                values = (
                    Path(snapshot.task.payload.source).name,
                    _status_text(snapshot.status.value),
                    _page_count(snapshot.result),
                    _error_text(snapshot, log_root=self.log_root),
                )
                for column, value in enumerate(values):
                    self.table.setItem(row, column, QTableWidgetItem(str(value)))
            self._update_result_actions()

        def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
            if self._queue_is_running():
                self.status_label.setText("\u8bf7\u5148\u53d6\u6d88\u6216\u7b49\u5f85\u5f53\u524d\u961f\u5217\u7ed3\u675f")
                event.ignore()
                return
            super().closeEvent(event)

    return MainWindow()


def run_main(
    queue: PdfTaskQueue,
    task_factory: Callable[[Path], PdfTask],
    *,
    output_root: Path | None = None,
    log_root: Path | None = None,
) -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ModuleNotFoundError as exc:
        raise RuntimeError("GUI requires the optional PySide6 dependency") from exc
    app = QApplication.instance() or QApplication([])
    window = build_main_window(queue, task_factory, output_root=output_root, log_root=log_root)
    window.show()
    return app.exec()


def _output_root_text(output_root: Path | None) -> str:
    if output_root is None:
        return "输出位置：完成后可从所选任务打开输出文件夹"
    return f"默认输出位置：{output_root}"


def _status_text(status: str) -> str:
    return {
        "queued": "等待处理",
        "running": "处理中",
        "paused": "已暂停",
        "completed": "已完成",
        "failed": "失败",
        "cancelled": "已取消",
    }.get(status, status)


def _page_count(result: object) -> str:
    if isinstance(result, dict):
        if "result" in result:
            return _page_count(result["result"])
        pages = result.get("pages")
        if isinstance(pages, int):
            return str(pages)
        if pages is not None:
            try:
                return str(len(pages))
            except TypeError:
                return ""
    pages = getattr(result, "pages", None)
    return "" if pages is None else str(len(pages))


def _error_text(snapshot: object, *, log_root: Path | None = None) -> str:
    review_count = _review_item_count(getattr(snapshot, "result", None))
    if review_count:
        return f"{review_count} 项待复核"
    error = getattr(snapshot, "error", None)
    if error is not None:
        payload = getattr(getattr(snapshot, "task", None), "payload", None)
        return user_error_summary(
            error,
            source=getattr(payload, "source", None),
            output_dir=getattr(payload, "output_dir", None),
            log_root=log_root,
        )
    return ""



def _needs_review_count_from_store(store: object, run_id: int) -> int:
    return sum(1 for _page_index, state in store.page_states(run_id) if state == "needs_review")

def _review_item_count(result: object) -> int:
    if isinstance(result, dict):
        persisted_count = result.get("needs_review_count")
        if isinstance(persisted_count, int):
            return persisted_count
        return _review_item_count(result.get("result"))
    pages = getattr(result, "pages", ()) if result is not None else ()
    return sum(
        1
        for page in pages
        if getattr(
            getattr(getattr(page, "validation_report", None), "status", None),
            "value",
            None,
        )
        in {"review", "page_review"}
    )
