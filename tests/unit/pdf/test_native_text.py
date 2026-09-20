from pathlib import Path

import pymupdf

from bankocr.domain.text_block import SourceType
from bankocr.pdf.native import NativeTextExtractor


def test_native_text_extractor_emits_pdf_coordinate_text_blocks(tmp_path: Path) -> None:
    source = tmp_path / "native.pdf"
    document = pymupdf.open()
    page = document.new_page(width=200, height=100)
    page.insert_text((20, 40), "2026-08-01 10.00", fontsize=12)
    document.save(source)
    document.close()

    blocks = NativeTextExtractor(source).extract_page(0)

    assert len(blocks) == 1
    assert blocks[0].source_type is SourceType.NATIVE_PDF
    assert blocks[0].confidence is None
    assert "2026-08-01" in blocks[0].text
    assert blocks[0].bbox[0] >= 20
