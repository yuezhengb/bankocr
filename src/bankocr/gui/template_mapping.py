"""Explicit GUI confirmation for a Run-scoped Temporary Template."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from bankocr.domain.text_block import TextBlock
from bankocr.parser.templates import ColumnDefinition
from bankocr.parser.temporary_template import TemporaryTemplateConfirmation


def build_temporary_template_dialog(
    run_id: int,
    blocks_by_page: Mapping[int, Sequence[TextBlock]],
    *,
    on_save: Callable[[TemporaryTemplateConfirmation], None],
    source_pdf: str | Path | None = None,
    initial_page: int | None = None,
):
    """Build a modal mapping dialog without making an automatic guess.

    The OCR blocks are displayed as evidence.  The operator must explicitly
    confirm header tokens, field names, and non-overlapping page-relative
    column boundaries before a ``TemporaryTemplateConfirmation`` is emitted.
    """

    pages = tuple(
        sorted(page_index for page_index, blocks in blocks_by_page.items() if blocks)
    )
    if not pages:
        raise ValueError("at least one page with OCR blocks is required")
    if initial_page not in pages:
        initial_page = pages[0]

    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QAbstractItemView,
            QComboBox,
            QDialog,
            QFormLayout,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMessageBox,
            QPushButton,
            QTableWidget,
            QTableWidgetItem,
            QVBoxLayout,
        )
    except ModuleNotFoundError as exc:
        raise RuntimeError("GUI requires the optional PySide6 dependency") from exc

    class TemplateMappingDialog(QDialog):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("确认 Temporary Template 列映射")
            self.setMinimumSize(760, 620)

            self.page_combo = QComboBox()
            for page_index in pages:
                self.page_combo.addItem(f"第 {page_index + 1} 页", page_index)
            self.page_combo.setCurrentIndex(pages.index(initial_page))
            self.page_combo.currentIndexChanged.connect(self._refresh_blocks)

            self.header_edit = QLineEdit()
            self.header_edit.setPlaceholderText("例如：日期,摘要,金额,余额")
            self.required_edit = QLineEdit("transaction_date,balance")
            self.reviewer_edit = QLineEdit("local-user")
            self.version_edit = QLineEdit("temporary-v1")
            self.row_strategy_combo = QComboBox()
            self.row_strategy_combo.addItems(("anchor_date", "positional", "grid"))

            form = QFormLayout()
            form.addRow("来源页（仅当前 Run）", self.page_combo)
            form.addRow("表头 tokens（逗号分隔）", self.header_edit)
            form.addRow("必需字段（逗号分隔）", self.required_edit)
            form.addRow("行策略", self.row_strategy_combo)
            form.addRow("确认人", self.reviewer_edit)
            form.addRow("模板版本", self.version_edit)

            evidence_label = QLabel(
                "OCR 块仅作为证据；以下列名和边界必须由复核员明确确认，系统不会把默认建议直接当成模板。"
            )
            evidence_label.setWordWrap(True)
            self.blocks_table = QTableWidget(0, 4)
            self.blocks_table.setHorizontalHeaderLabels(("块", "文字", "bbox（PDF）", "中心 X 比例"))
            self.blocks_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self.blocks_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

            columns_label = QLabel("列映射（left/right 为 0–1 的页面横向比例，右边界不包含）")
            columns_label.setWordWrap(True)
            self.columns_table = QTableWidget(0, 3)
            self.columns_table.setHorizontalHeaderLabels(("字段名", "left_ratio", "right_ratio"))
            self.columns_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.columns_table.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
            for name, left, right in _default_columns():
                self._append_column(name, left, right)

            add_column = QPushButton("添加列")
            remove_column = QPushButton("删除选中列")
            add_column.clicked.connect(lambda: self._append_column("", "", ""))
            remove_column.clicked.connect(self._remove_column)
            column_controls = QHBoxLayout()
            column_controls.addWidget(add_column)
            column_controls.addWidget(remove_column)
            column_controls.addStretch(1)

            save_button = QPushButton("确认并保存 Temporary Template")
            cancel_button = QPushButton("取消")
            save_button.clicked.connect(self._save)
            cancel_button.clicked.connect(self.reject)
            action_controls = QHBoxLayout()
            action_controls.addStretch(1)
            action_controls.addWidget(cancel_button)
            action_controls.addWidget(save_button)

            layout = QVBoxLayout(self)
            layout.addLayout(form)
            layout.addWidget(evidence_label)
            layout.addWidget(self.blocks_table)
            layout.addWidget(columns_label)
            layout.addWidget(self.columns_table)
            layout.addLayout(column_controls)
            layout.addLayout(action_controls)
            self._refresh_blocks()

        def _selected_page(self) -> int:
            return int(self.page_combo.currentData())

        def _refresh_blocks(self) -> None:
            page_index = self._selected_page()
            blocks = tuple(blocks_by_page[page_index])
            page_width = _page_width(source_pdf, page_index, blocks)
            self.blocks_table.setRowCount(len(blocks))
            for row, block in enumerate(blocks):
                left, top, right, bottom = block.bbox
                values = (
                    row,
                    block.text,
                    f"({left:.2f}, {top:.2f}, {right:.2f}, {bottom:.2f})",
                    f"{((left + right) / 2.0 / page_width):.4f}",
                )
                for column, value in enumerate(values):
                    self.blocks_table.setItem(row, column, QTableWidgetItem(str(value)))
            if not self.header_edit.text().strip():
                self.header_edit.setText(",".join(_suggest_headers(blocks)))

        def _append_column(self, name: str, left: str, right: str) -> None:
            row = self.columns_table.rowCount()
            self.columns_table.insertRow(row)
            for column, value in enumerate((name, left, right)):
                self.columns_table.setItem(row, column, QTableWidgetItem(str(value)))

        def _remove_column(self) -> None:
            row = self.columns_table.currentRow()
            if row < 0:
                row = self.columns_table.rowCount() - 1
            if row >= 0:
                self.columns_table.removeRow(row)

        def _save(self) -> None:
            try:
                columns = tuple(self._read_columns())
                headers = _split_values(self.header_edit.text())
                required = _split_values(self.required_edit.text())
                confirmation = TemporaryTemplateConfirmation(
                    run_id=run_id,
                    source_page_index=self._selected_page(),
                    header_tokens=headers,
                    columns=columns,
                    required_fields=required,
                    confirmed_by=self.reviewer_edit.text().strip(),
                    row_strategy=self.row_strategy_combo.currentText(),
                    version=self.version_edit.text().strip(),
                )
                on_save(confirmation)
            except Exception as exc:  # validation and persistence errors stay visible to the operator
                QMessageBox.warning(self, "Temporary Template 未保存", str(exc))
                return
            self.accept()

        def _read_columns(self) -> tuple[ColumnDefinition, ...]:
            columns: list[ColumnDefinition] = []
            for row in range(self.columns_table.rowCount()):
                values = tuple(
                    self.columns_table.item(row, column).text().strip()
                    if self.columns_table.item(row, column) is not None
                    else ""
                    for column in range(3)
                )
                if not any(values):
                    continue
                if not all(values):
                    raise ValueError(f"第 {row + 1} 行列映射必须完整填写")
                try:
                    columns.append(ColumnDefinition(values[0], float(values[1]), float(values[2])))
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"第 {row + 1} 行列映射无效: {exc}") from exc
            return tuple(columns)

    return TemplateMappingDialog()


def _default_columns() -> tuple[tuple[str, str, str], ...]:
    """Return editable suggestions, never an implicit parser decision."""

    return (
        ("transaction_date", "0.00", "0.30"),
        ("transaction_amount", "0.30", "0.70"),
        ("balance", "0.70", "1.00"),
    )


def _suggest_headers(blocks: Sequence[TextBlock]) -> tuple[str, ...]:
    values: list[str] = []
    for block in sorted(blocks, key=lambda item: (item.bbox[1], item.bbox[0])):
        text = block.text.strip()
        if text and text not in values:
            values.append(text)
        if len(values) >= 8:
            break
    return tuple(values)


def _split_values(value: str) -> tuple[str, ...]:
    values = tuple(item.strip() for item in value.split(",") if item.strip())
    if not values:
        raise ValueError("逗号分隔值不能为空")
    return values


def _page_width(
    source_pdf: str | Path | None,
    page_index: int,
    blocks: Sequence[TextBlock],
) -> float:
    if source_pdf is not None:
        source = Path(source_pdf)
        if source.is_file():
            try:
                import pymupdf

                with pymupdf.open(source) as document:
                    return max(float(document[page_index].rect.width), 1.0)
            except Exception:
                pass
    return max((block.bbox[2] for block in blocks), default=1.0)
