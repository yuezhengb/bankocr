from pathlib import Path

import pymupdf
import pytest

from bankocr.domain.coordinates import Point
from bankocr.domain.text_block import SourceType, TextBlock
from bankocr.export.comparison_pdf import ComparisonPdfExporter
from bankocr.parser.models import FieldValue, TransactionCandidate


def _block(text: str) -> TextBlock:
    return TextBlock(
        text=text,
        raw_text=text,
        polygon=(Point(20, 20), Point(80, 20), Point(80, 35), Point(20, 35)),
        confidence=0.9,
        source_type=SourceType.OCR,
        page_index=0,
        engine_id="test",
    )


def _candidate(*, located: bool = True) -> TransactionCandidate:
    return TransactionCandidate(
        page_index=0,
        row_index=1,
        parser_id="test:v1",
        fields={
            "amount": FieldValue(
                "10.00",
                "10.00",
                source_block_indices=(0,) if located else (),
            )
        },
    )


def _source_pdf(path: Path) -> bytes:
    document = pymupdf.open()
    page = document.new_page(width=200, height=100)
    page.insert_text((20, 50), "original", fontsize=10)
    document.save(path)
    document.close()
    return path.read_bytes()


def test_comparison_pdf_preserves_source_and_adds_searchable_text_and_marker(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "source.comparison.pdf"
    original_bytes = _source_pdf(source)

    ComparisonPdfExporter().export(
        source,
        output,
        (_candidate(),),
        {0: (_block("10.00"),)},
    )

    assert source.read_bytes() == original_bytes
    source_document = pymupdf.open(source)
    comparison_document = pymupdf.open(output)
    try:
        assert comparison_document.page_count == source_document.page_count
        assert "10.00" in comparison_document[0].get_text()
        assert "T0001" in comparison_document[0].get_text()
        assert len(comparison_document[0].get_drawings()) > len(source_document[0].get_drawings())
    finally:
        source_document.close()
        comparison_document.close()


def test_comparison_pdf_does_not_guess_a_marker_without_source_location(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "source.comparison.pdf"
    _source_pdf(source)

    ComparisonPdfExporter().export(
        source,
        output,
        (_candidate(located=False),),
        {0: (_block("10.00"),)},
    )

    document = pymupdf.open(output)
    try:
        assert "10.00" in document[0].get_text()
        assert "T0001" not in document[0].get_text()
        assert document[0].get_drawings() == []
    finally:
        document.close()


def test_comparison_pdf_does_not_overwrite_source(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    _source_pdf(source)

    with pytest.raises(ValueError, match="must not overwrite"):
        ComparisonPdfExporter().export(
            source,
            source,
            (_candidate(),),
            {0: (_block("10.00"),)},
        )
