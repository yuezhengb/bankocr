from io import BytesIO
from pathlib import Path

import pymupdf
from PIL import Image

from bankocr.domain.page import PageKind
from bankocr.pdf.classifier import PageClassifier
from bankocr.pdf.reader import PdfReader


def _image_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (32, 32), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _make_fixture(path: Path) -> None:
    document = pymupdf.open()
    native = document.new_page()
    native.insert_text((72, 72), "交易日期 余额")
    scan = document.new_page()
    scan.insert_image(scan.rect, stream=_image_bytes())
    hybrid = document.new_page()
    hybrid.insert_text((72, 72), "余额")
    hybrid.insert_image(hybrid.rect, stream=_image_bytes())
    document.new_page()
    document.save(path)
    document.close()


def test_pdf_reader_and_classifier_route_each_page(tmp_path):
    path = tmp_path / "fixture.pdf"
    _make_fixture(path)

    signals = list(PdfReader(path).iter_signals())
    results = [PageClassifier().classify(item) for item in signals]

    assert [result.kind for result in results] == [
        PageKind.NATIVE_TEXT,
        PageKind.SCAN_IMAGE,
        PageKind.HYBRID,
        PageKind.BLANK,
    ]
    assert [result.page_index for result in results] == [0, 1, 2, 3]


def test_pdf_reader_rejects_non_pdf_path(tmp_path):
    path = tmp_path / "missing.pdf"

    try:
        list(PdfReader(path).iter_signals())
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("expected missing PDF to fail before page iteration")
