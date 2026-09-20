from bankocr.domain.text_block import SourceType, TextBlock
from bankocr.domain.coordinates import Point


def _polygon():
    return (
        Point(10.0, 20.0),
        Point(40.0, 20.0),
        Point(40.0, 30.0),
        Point(10.0, 30.0),
    )


def test_text_block_preserves_raw_text_and_exposes_bounding_box():
    block = TextBlock(
        text="50000.00",
        raw_text="5O000.00",
        polygon=_polygon(),
        confidence=0.91,
        source_type=SourceType.OCR,
        page_index=3,
        engine_id="rapidocr:pp-ocrv6-small",
    )

    assert block.text == "50000.00"
    assert block.raw_text == "5O000.00"
    assert block.bbox == (10.0, 20.0, 40.0, 30.0)
    assert block.page_index == 3


def test_text_block_rejects_confidence_outside_zero_to_one():
    try:
        TextBlock(
            text="x",
            raw_text="x",
            polygon=_polygon(),
            confidence=1.01,
            source_type=SourceType.OCR,
            page_index=0,
            engine_id="fake",
        )
    except ValueError as exc:
        assert "confidence" in str(exc)
    else:
        raise AssertionError("expected ValueError for invalid confidence")
