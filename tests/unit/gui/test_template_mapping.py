import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

from bankocr.domain.coordinates import Point
from bankocr.domain.text_block import SourceType, TextBlock
from bankocr.gui.template_mapping import build_temporary_template_dialog


def _block(text: str, left: float, top: float, right: float) -> TextBlock:
    return TextBlock(
        text=text,
        raw_text=text,
        polygon=(
            Point(left, top),
            Point(right, top),
            Point(right, top + 8),
            Point(left, top + 8),
        ),
        confidence=0.99,
        source_type=SourceType.OCR,
        page_index=0,
        engine_id="test",
    )


def test_temporary_template_dialog_requires_explicit_mapping_and_emits_confirmation() -> None:
    app = QApplication.instance() or QApplication([])
    blocks = {
        0: (
            _block("日期", 0, 10, 20),
            _block("金额", 30, 10, 50),
            _block("余额", 70, 10, 90),
        )
    }
    captured = []
    dialog = build_temporary_template_dialog(
        12,
        blocks,
        on_save=captured.append,
    )

    dialog.header_edit.setText("日期,金额,余额")
    dialog.required_edit.setText("transaction_date,balance")
    dialog.columns_table.item(0, 0).setText("transaction_date")
    dialog.columns_table.item(0, 1).setText("0")
    dialog.columns_table.item(0, 2).setText("0.3")
    dialog.columns_table.item(1, 0).setText("transaction_amount")
    dialog.columns_table.item(1, 1).setText("0.3")
    dialog.columns_table.item(1, 2).setText("0.7")
    dialog.columns_table.item(2, 0).setText("balance")
    dialog.columns_table.item(2, 1).setText("0.7")
    dialog.columns_table.item(2, 2).setText("1")

    dialog._save()
    app.processEvents()

    assert len(captured) == 1
    assert captured[0].template_id == "temporary:run-12:page-0"
    assert tuple(column.name for column in captured[0].columns) == (
        "transaction_date",
        "transaction_amount",
        "balance",
    )
    dialog.close()


def test_temporary_template_dialog_rejects_missing_page_blocks() -> None:
    with pytest.raises(ValueError, match="at least one page"):
        build_temporary_template_dialog(1, {0: ()}, on_save=lambda _: None)
