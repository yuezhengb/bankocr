import os
from pathlib import Path

import pymupdf
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QPushButton

from bankocr.domain.coordinates import Point
from bankocr.domain.text_block import SourceType, TextBlock
from bankocr.gui.app import build_review_window
from bankocr.parser.models import FieldValue, TransactionCandidate


def test_review_window_renders_the_selected_source_crop(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    document = pymupdf.open()
    page = document.new_page(width=200, height=100)
    page.insert_text((20, 30), "10.00")
    document.save(source)
    document.close()
    block = TextBlock(
        text="10.00",
        raw_text="10.00",
        polygon=(Point(15, 15), Point(60, 15), Point(60, 35), Point(15, 35)),
        confidence=0.99,
        source_type=SourceType.OCR,
        page_index=0,
        engine_id="test",
    )
    candidate = TransactionCandidate(
        page_index=0,
        row_index=0,
        parser_id="known:v1",
        fields={"amount": FieldValue("10.00", "10.00", source_block_indices=(0,))},
    )
    app = QApplication.instance() or QApplication([])
    window = build_review_window(
        (candidate,),
        source_pdf=source,
        blocks_by_page={0: (block,)},
    )

    window._show_source(0)
    app.processEvents()

    assert window.image_label.pixmap() is not None
    window.close()


def test_review_window_exposes_explicit_temporary_template_mapping(tmp_path: Path) -> None:
    block = TextBlock(
        text="日期",
        raw_text="日期",
        polygon=(Point(15, 15), Point(60, 15), Point(60, 35), Point(15, 35)),
        confidence=0.99,
        source_type=SourceType.OCR,
        page_index=0,
        engine_id="test",
    )
    candidate = TransactionCandidate(
        page_index=0,
        row_index=0,
        parser_id="known:v1",
        fields={"amount": FieldValue("10.00", "10.00")},
    )
    app = QApplication.instance() or QApplication([])
    captured = []
    window = build_review_window(
        (candidate,),
        on_confirm_temporary_template=captured.append,
        temporary_template_run_id=3,
        blocks_by_page={0: (block,)},
    )

    assert any(
        button.text() == "确认 Temporary Template"
        for button in window.findChildren(QPushButton)
    )
    window._open_template_mapping()
    app.processEvents()
    assert len(window._template_windows) == 1
    window._template_windows[0].close()
    window.close()
