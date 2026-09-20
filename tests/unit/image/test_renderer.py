from pathlib import Path

import pymupdf

from bankocr.domain.coordinates import Point
from bankocr.image.renderer import PdfRenderer


def test_pdf_renderer_returns_image_with_reversible_pdf_mapping(tmp_path: Path):
    path = tmp_path / "render.pdf"
    document = pymupdf.open()
    page = document.new_page(width=72, height=72)
    page.insert_text((10, 20), "OCR")
    document.save(path)
    document.close()

    image = PdfRenderer(path).render(page_index=0, dpi=144)

    assert image.page_index == 0
    assert image.width_px == 144
    assert image.height_px == 144
    assert image.transform.to_pdf(Point(72.0, 72.0)) == Point(36.0, 36.0)
    assert image.payload.shape[:2] == (144, 144)


def test_pdf_renderer_preserves_mapping_for_rotated_page(tmp_path: Path):
    source = tmp_path / "rotated.pdf"
    document = pymupdf.open()
    page = document.new_page(width=200, height=100)
    page.set_rotation(90)
    document.save(source)
    document.close()

    image = PdfRenderer(source).render(0, dpi=72)

    assert image.width_px == 100
    assert image.height_px == 200
    assert image.transform.to_pdf(Point(70.0, 20.0)).x == 20.0
    assert image.transform.to_pdf(Point(70.0, 20.0)).y == 30.0
