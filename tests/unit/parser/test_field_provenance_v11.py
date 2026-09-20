from bankocr.domain.coordinates import Point
from bankocr.domain.text_block import SourceSpan
from bankocr.parser.models import FieldValue


def test_field_value_preserves_multiple_field_level_source_spans() -> None:
    polygon = (Point(1, 2), Point(3, 2), Point(3, 4), Point(1, 4))
    spans = (
        SourceSpan(0, polygon, "p000:ocr:0001"),
        SourceSpan(0, polygon, "p000:ocr:0002"),
    )

    value = FieldValue("甲 乙", "甲 乙", source_spans=spans)

    assert value.source_spans == spans
    assert tuple(span.text_block_id for span in value.source_spans) == (
        "p000:ocr:0001",
        "p000:ocr:0002",
    )
