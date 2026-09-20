from io import BytesIO
from pathlib import Path

import pymupdf
from PIL import Image

from bankocr.benchmark.baseline import OCRBaselineRunner
from bankocr.domain.coordinates import CoordinateTransform, Point
from bankocr.domain.text_block import SourceType, TextBlock
from bankocr.image.types import PageImage
from bankocr.ocr.result import OCRPageResult


def _scan_pdf(path: Path):
    image_buffer = BytesIO()
    Image.new("RGB", (16, 16), "white").save(image_buffer, format="PNG")
    document = pymupdf.open()
    page = document.new_page()
    page.insert_image(page.rect, stream=image_buffer.getvalue())
    document.save(path)
    document.close()


class FakeRenderer:
    def render(self, page_index: int, *, dpi: int):
        return PageImage(
            page_index=page_index,
            width_px=16,
            height_px=16,
            dpi=dpi,
            payload=object(),
            transform=CoordinateTransform.scale(1.0, 1.0),
        )


class FakeBackend:
    engine_id = "fake"

    def recognize(self, image, options):
        block = TextBlock(
            text="ABC",
            raw_text="ABC",
            polygon=(Point(0, 0), Point(1, 0), Point(1, 1), Point(0, 1)),
            confidence=0.99,
            source_type=SourceType.OCR,
            page_index=image.page_index,
            engine_id="fake",
        )
        return OCRPageResult(image.page_index, (block,), "fake")


def test_baseline_runner_processes_scan_pages_without_retaining_page_images(tmp_path):
    path = tmp_path / "scan.pdf"
    _scan_pdf(path)

    report = OCRBaselineRunner(
        backend=FakeBackend(),
        renderer_factory=lambda _: FakeRenderer(),
    ).run(path, dpi=200)

    assert report.page_count == 1
    assert report.scan_page_count == 1
    assert report.total_blocks == 1
    assert report.pages[0].page_index == 0
    assert report.pages[0].elapsed_seconds >= 0
