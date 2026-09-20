"""Optional PySide6 review window; review semantics stay in ReviewSession."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Mapping, Sequence

from bankocr.domain.text_block import TextBlock
from bankocr.parser.models import FieldValue, TransactionCandidate
from bankocr.parser.temporary_template import TemporaryTemplateConfirmation
from bankocr.pipeline.review_service import ReviewService
from bankocr.storage.project_store import ProjectStore
from .review_model import ReviewSession


def build_review_window(
    candidates: tuple[TransactionCandidate, ...] | list[TransactionCandidate],
    *,
    on_save: Callable[[tuple[TransactionCandidate, ...]], None] | None = None,
    on_save_session: Callable[[ReviewSession], None] | None = None,
    on_confirm_temporary_template: Callable[[TemporaryTemplateConfirmation], None]
    | None = None,
    temporary_template_run_id: int | None = None,
    temporary_template_page: int | None = None,
    source_pdf: str | Path | None = None,
    blocks_by_page: Mapping[int, Sequence[TextBlock]] | None = None,
):
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage, QKeySequence, QPixmap, QShortcut
        from PySide6.QtWidgets import (
            QApplication,
            QMainWindow,
            QPushButton,
            QLabel,
            QTableWidget,
            QTableWidgetItem,
            QVBoxLayout,
            QWidget,
            QInputDialog,
            QMessageBox,
        )
    except ModuleNotFoundError as exc:
        raise RuntimeError("GUI requires the optional PySide6 dependency") from exc

    class ReviewWindow(QMainWindow):
        def __init__(self, initial: tuple[TransactionCandidate, ...]) -> None:
            super().__init__()
            self.session = ReviewSession(initial)
            self.table = QTableWidget()
            self.table.setColumnCount(8)
            self.table.setHorizontalHeaderLabels(
                ["页码", "行号", "字段", "原始 OCR", "二次 OCR", "解析建议", "最终值", "状态"]
            )
            self.source_label = QLabel("选择一行查看页码、OCR 层和来源块")
            self.source_label.setWordWrap(True)
            self.image_label = QLabel("来源图像预览")
            self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.image_label.setMinimumHeight(180)
            self.table.currentCellChanged.connect(self._show_source)
            QShortcut(QKeySequence("Return"), self, activated=self._accept_selected)
            QShortcut(QKeySequence("E"), self, activated=self._edit_selected)
            QShortcut(QKeySequence("N"), self, activated=self._next_row)
            QShortcut(QKeySequence("P"), self, activated=self._previous_row)
            accept_button = QPushButton("接受选中行")
            reject_button = QPushButton("驳回选中行")
            accept_button.clicked.connect(self._accept_selected)
            reject_button.clicked.connect(self._reject_selected)
            move_up_button = QPushButton("Move up")
            move_down_button = QPushButton("Move down")
            merge_button = QPushButton("Merge with next")
            split_button = QPushButton("Split fields")
            duplicate_button = QPushButton("Mark duplicate")
            add_button = QPushButton("Add missing row")
            move_up_button.clicked.connect(lambda: self._move_selected(-1))
            move_down_button.clicked.connect(lambda: self._move_selected(1))
            merge_button.clicked.connect(self._merge_selected)
            split_button.clicked.connect(self._split_selected)
            duplicate_button.clicked.connect(self._duplicate_selected)
            add_button.clicked.connect(self._add_missing)
            central = QWidget()
            layout = QVBoxLayout(central)
            layout.addWidget(self.table)
            layout.addWidget(self.image_label)
            layout.addWidget(self.source_label)
            layout.addWidget(accept_button)
            layout.addWidget(reject_button)
            layout.addWidget(move_up_button)
            layout.addWidget(move_down_button)
            layout.addWidget(merge_button)
            layout.addWidget(split_button)
            layout.addWidget(duplicate_button)
            layout.addWidget(add_button)
            if on_save is not None or on_save_session is not None:
                save_button = QPushButton("保存复核")
                save_button.clicked.connect(self._save)
                layout.addWidget(save_button)
            self.setWindowTitle("BankOCR 复核")
            self.setCentralWidget(central)
            self._reload()
            self._template_windows = []
            if (
                on_confirm_temporary_template is not None
                and temporary_template_run_id is not None
                and blocks_by_page
            ):
                template_button = QPushButton("确认 Temporary Template")
                template_button.clicked.connect(self._open_template_mapping)
                layout.addWidget(template_button)

        def _reload(self) -> None:
            self.table.setRowCount(sum(len(candidate.fields) for candidate in self.session.candidates))
            row = 0
            for candidate_index, candidate in enumerate(self.session.candidates):
                for field_name, field in candidate.fields:
                    values = (
                        candidate.page_index,
                        candidate.row_index,
                        field_name,
                        field.raw_text,
                        field.secondary_text or "",
                        field.suggested_text or "",
                        field.final_text or "",
                        candidate.status.value,
                    )
                    for column, value in enumerate(values):
                        item = QTableWidgetItem(str(value))
                        item.setData(Qt.ItemDataRole.UserRole, candidate_index)
                        item.setData(Qt.ItemDataRole.UserRole + 1, field_name)
                        if column != 6:
                            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        self.table.setItem(row, column, item)
                    row += 1
            if self.table.rowCount():
                self.table.selectRow(min(self.table.currentRow(), self.table.rowCount() - 1))

        def _selected(self) -> tuple[int, str] | None:
            row = self.table.currentRow()
            if row < 0:
                return None
            item = self.table.item(row, 0)
            return int(item.data(Qt.ItemDataRole.UserRole)), str(
                item.data(Qt.ItemDataRole.UserRole + 1)
            )

        def _accept_selected(self) -> None:
            selected = self._selected()
            if selected is None:
                return
            candidate_index, field_name = selected
            row = self.table.currentRow()
            final_value = self.table.item(row, 6).text().strip()
            if final_value:
                self.session = self.session.edit_field(candidate_index, field_name, final_value)
            self.session = self.session.accept(candidate_index)
            self._reload()

        def _reject_selected(self) -> None:
            selected = self._selected()
            if selected is not None:
                self.session = self.session.reject(selected[0])
                self._reload()

        def _move_selected(self, delta: int) -> None:
            selected = self._selected()
            if selected is None:
                return
            candidate_index = selected[0]
            target = candidate_index + delta
            try:
                self.session = self.session.move_candidate(candidate_index, target)
            except (IndexError, ValueError) as exc:
                self._show_structure_error(exc)
                return
            self._reload()

        def _merge_selected(self) -> None:
            selected = self._selected()
            if selected is None:
                return
            try:
                self.session = self.session.merge_candidates(selected[0], selected[0] + 1)
            except (IndexError, ValueError) as exc:
                self._show_structure_error(exc)
                return
            self._reload()

        def _split_selected(self) -> None:
            selected = self._selected()
            if selected is None:
                return
            candidate = self.session.candidates[selected[0]]
            names, accepted = QInputDialog.getText(
                self,
                "Split fields",
                "Fields to move, comma separated:",
                text=", ".join(name for name, _ in candidate.fields),
            )
            if not accepted:
                return
            try:
                self.session = self.session.split_candidate(
                    selected[0],
                    tuple(name.strip() for name in names.split(",") if name.strip()),
                )
            except (IndexError, KeyError, ValueError) as exc:
                self._show_structure_error(exc)
                return
            self._reload()

        def _duplicate_selected(self) -> None:
            selected = self._selected()
            if selected is None:
                return
            target, accepted = QInputDialog.getInt(
                self,
                "Mark duplicate",
                "Target candidate index (0-based):",
                value=max(0, selected[0] - 1),
                minValue=0,
                maxValue=max(0, len(self.session.candidates) - 1),
            )
            if not accepted:
                return
            try:
                self.session = self.session.mark_duplicate(selected[0], target)
            except (IndexError, ValueError) as exc:
                self._show_structure_error(exc)
                return
            self._reload()

        def _add_missing(self) -> None:
            selected = self._selected()
            page_index = (
                self.session.candidates[selected[0]].page_index
                if selected is not None
                else 0
            )
            text, accepted = QInputDialog.getText(
                self,
                "Add missing row",
                "Fields as name=value, separated by semicolons:",
            )
            if not accepted:
                return
            fields: dict[str, FieldValue] = {}
            try:
                for item in text.split(";"):
                    name, value = item.split("=", 1)
                    name, value = name.strip(), value.strip()
                    if not name or not value:
                        raise ValueError("every field must contain a non-empty name and value")
                    fields[name] = FieldValue(value, value)
                candidate = TransactionCandidate(
                    page_index=page_index,
                    row_index=0,
                    parser_id="review:manual",
                    fields=fields,
                )
                position = selected[0] + 1 if selected is not None else None
                self.session = self.session.add_candidate(candidate, position)
            except (IndexError, ValueError) as exc:
                self._show_structure_error(exc)
                return
            self._reload()

        def _show_structure_error(self, error: Exception) -> None:
            QMessageBox.warning(self, "Structure review", str(error))

        def _open_template_mapping(self) -> None:
            from .template_mapping import build_temporary_template_dialog

            try:
                dialog = build_temporary_template_dialog(
                    temporary_template_run_id,
                    blocks_by_page or {},
                    on_save=on_confirm_temporary_template,
                    source_pdf=source_pdf,
                    initial_page=temporary_template_page,
                )
            except (RuntimeError, ValueError) as exc:
                self._show_structure_error(exc)
                return
            self._template_windows.append(dialog)
            dialog.finished.connect(
                lambda *_: self._template_windows.remove(dialog)
                if dialog in self._template_windows
                else None
            )
            dialog.show()

        def _show_source(self, row: int, *_args) -> None:
            if row < 0:
                return
            item = self.table.item(row, 0)
            if item is None:
                return
            candidate_index = int(item.data(Qt.ItemDataRole.UserRole))
            field_name = str(item.data(Qt.ItemDataRole.UserRole + 1))
            candidate = self.session.candidates[candidate_index]
            field = candidate.field(field_name)
            self.source_label.setText(
                f"来源：第 {candidate.page_index + 1} 页 / 行 {candidate.row_index} / {field_name}；"
                f"raw={field.raw_text}；secondary={field.secondary_text or ''}；"
                f"suggested={field.suggested_text or ''}；"
                f"final={field.final_text or ''}；block={','.join(map(str, field.source_block_indices)) or '—'}"
            )
            self._show_image(candidate, field)

        def _show_image(self, candidate, field) -> None:
            source = None if source_pdf is None else Path(source_pdf)
            if source is None or not source.is_file():
                self.image_label.setText("未找到来源 PDF，仍可按文字证据复核")
                return
            try:
                import pymupdf

                with pymupdf.open(source) as document:
                    page = document[candidate.page_index]
                    clip = page.rect
                    blocks = (blocks_by_page or {}).get(candidate.page_index, ())
                    source_blocks = [
                        blocks[index]
                        for index in field.source_block_indices
                        if 0 <= index < len(blocks)
                    ]
                    if source_blocks:
                        clip = pymupdf.Rect(
                            min(block.bbox[0] for block in source_blocks) - 12,
                            min(block.bbox[1] for block in source_blocks) - 12,
                            max(block.bbox[2] for block in source_blocks) + 12,
                            max(block.bbox[3] for block in source_blocks) + 12,
                        ) & page.rect
                    pixmap = page.get_pixmap(
                        matrix=pymupdf.Matrix(2, 2),
                        clip=clip,
                        alpha=False,
                    )
                image_format = (
                    QImage.Format.Format_Grayscale8
                    if pixmap.n == 1
                    else QImage.Format.Format_RGB888
                )
                image = QImage(
                    pixmap.samples,
                    pixmap.width,
                    pixmap.height,
                    pixmap.stride,
                    image_format,
                ).copy()
                rendered = QPixmap.fromImage(image).scaled(
                    max(320, self.image_label.width()),
                    260,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.image_label.setPixmap(rendered)
            except Exception as exc:
                self.image_label.setText(f"来源图像加载失败：{type(exc).__name__}")

        def _edit_selected(self) -> None:
            row = self.table.currentRow()
            if row < 0:
                return
            item = self.table.item(row, 6)
            if item is not None:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                self.table.editItem(item)

        def _next_row(self) -> None:
            row = self.table.currentRow()
            if row >= 0 and row + 1 < self.table.rowCount():
                self.table.selectRow(row + 1)

        def _previous_row(self) -> None:
            row = self.table.currentRow()
            if row > 0:
                self.table.selectRow(row - 1)

        def _save(self) -> None:
            if on_save_session is not None:
                on_save_session(self.session)
            elif on_save is not None:
                on_save(self.session.candidates)

    return ReviewWindow(tuple(candidates))


def run_review(
    candidates: tuple[TransactionCandidate, ...] | list[TransactionCandidate],
    *,
    on_save: Callable[[tuple[TransactionCandidate, ...]], None] | None = None,
    on_save_session: Callable[[ReviewSession], None] | None = None,
    on_confirm_temporary_template: Callable[[TemporaryTemplateConfirmation], None]
    | None = None,
    temporary_template_run_id: int | None = None,
    temporary_template_page: int | None = None,
    source_pdf: str | Path | None = None,
    blocks_by_page: Mapping[int, Sequence[TextBlock]] | None = None,
) -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ModuleNotFoundError as exc:
        raise RuntimeError("GUI requires the optional PySide6 dependency") from exc
    app = QApplication.instance() or QApplication([])
    window = build_review_window(
        candidates,
        on_save=on_save,
        on_save_session=on_save_session,
        on_confirm_temporary_template=on_confirm_temporary_template,
        temporary_template_run_id=temporary_template_run_id,
        temporary_template_page=temporary_template_page,
        source_pdf=source_pdf,
        blocks_by_page=blocks_by_page,
    )
    window.show()
    return app.exec()


def run_persisted_review(store: ProjectStore, run_id: int) -> int:
    """Open the optional UI and persist every explicit save into a ProjectStore."""

    candidates = store.load_candidates(run_id)
    review_service = ReviewService(store)

    def save_temporary_template(confirmation: TemporaryTemplateConfirmation) -> None:
        store.save_temporary_template(confirmation.to_record())
        store.requeue_review_pages(run_id)

    return run_review(
        candidates,
        on_save=lambda reviewed: review_service.save(run_id, reviewed),
        on_save_session=lambda session: review_service.save_session(run_id, session),
        on_confirm_temporary_template=save_temporary_template,
        temporary_template_run_id=run_id,
        temporary_template_page=next(
            (page_index for page_index, status in store.page_states(run_id) if status == "needs_review"),
            None,
        ),
        source_pdf=store.get_run_source_path(run_id),
        blocks_by_page=store.load_ocr_blocks(run_id),
    )
