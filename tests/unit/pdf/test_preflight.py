from pathlib import Path

import pymupdf
import pytest

from bankocr.pdf.preflight import PdfPreflightError, run_preflight


def test_preflight_reports_blank_rotated_and_repeated_pages(tmp_path: Path) -> None:
    source = tmp_path / "input.pdf"
    document = pymupdf.open()
    first = document.new_page(width=200, height=100)
    first.insert_text((20, 20), "same")
    second = document.new_page(width=200, height=100)
    second.insert_text((20, 20), "same")
    second.set_rotation(90)
    document.new_page(width=200, height=100)
    document.save(source)
    document.close()

    result = run_preflight(source, output_dir=tmp_path / "output")

    assert result.page_count == 3
    assert result.blank_pages == (2,)
    assert result.rotated_pages == (1,)
    assert result.repeated_pages == ((0, 1),)
    assert result.source_sha256


def test_preflight_rejects_empty_pdf_and_source_overwrite(tmp_path: Path) -> None:
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    with pytest.raises(PdfPreflightError, match="empty"):
        run_preflight(empty)

    source = tmp_path / "source.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(source)
    document.close()
    with pytest.raises(PdfPreflightError, match="overwrite"):
        run_preflight(source, output_paths=(source,))
