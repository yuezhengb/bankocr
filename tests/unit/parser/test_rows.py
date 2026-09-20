from bankocr.domain.coordinates import Point
from bankocr.domain.text_block import SourceType, TextBlock
from bankocr.parser.rows import RowGroupingOptions, group_text_blocks


def _block(text: str, x: float, y: float, width: float = 20.0, height: float = 8.0) -> TextBlock:
    return TextBlock(
        text=text,
        raw_text=text,
        polygon=(
            Point(x, y),
            Point(x + width, y),
            Point(x + width, y + height),
            Point(x, y + height),
        ),
        confidence=0.95,
        source_type=SourceType.OCR,
        page_index=0,
        engine_id="test",
    )


def test_row_grouping_uses_vertical_overlap_then_preserves_x_order() -> None:
    blocks = (
        _block("amount", 80, 102),
        _block("date", 10, 100),
        _block("next", 10, 140),
        _block("description", 40, 101, width=30),
    )

    rows = group_text_blocks(blocks, RowGroupingOptions(y_tolerance=4.0))

    assert len(rows) == 2
    assert [block.text for block in rows[0].blocks] == ["date", "description", "amount"]
    assert [block.text for block in rows[1].blocks] == ["next"]


def test_row_grouping_rejects_blocks_from_other_pages() -> None:
    blocks = (_block("page0", 0, 0),)
    other = _block("page1", 20, 0)
    other = TextBlock(
        text=other.text,
        raw_text=other.raw_text,
        polygon=other.polygon,
        confidence=other.confidence,
        source_type=other.source_type,
        page_index=1,
        engine_id=other.engine_id,
    )

    try:
        group_text_blocks(blocks + (other,))
    except ValueError as exc:
        assert "page" in str(exc)
    else:
        raise AssertionError("expected page mismatch to fail closed")
