from bankocr.domain.coordinates import Point
from bankocr.domain.text_block import SourceSpan, SourceType, TextBlock


def test_text_block_has_stable_identity_and_source_span_geometry():
    polygon = (
        Point(10.0, 20.0),
        Point(40.0, 20.0),
        Point(40.0, 30.0),
        Point(10.0, 30.0),
    )
    block = TextBlock(
        text="50000.00",
        raw_text="5O000.00",
        polygon=polygon,
        confidence=0.91,
        source_type=SourceType.OCR,
        page_index=3,
        engine_id="rapidocr",
        text_block_id="p003:ocr:0007",
    )

    span = SourceSpan.from_block(block)

    assert block.text_block_id == "p003:ocr:0007"
    assert span.text_block_id == block.text_block_id
    assert span.page_index == 3
    assert span.polygon == block.polygon
    assert span.bbox == block.bbox
