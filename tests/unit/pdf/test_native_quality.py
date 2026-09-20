from bankocr.domain.coordinates import Point
from bankocr.domain.text_block import SourceType, TextBlock
from bankocr.pdf.native_quality import NativeTextQualityGate, deduplicate_blocks


def _block(
    text: str,
    *,
    bbox: tuple[float, float, float, float] = (10, 10, 40, 20),
    source_type: SourceType = SourceType.NATIVE_PDF,
    block_id: str = "block",
) -> TextBlock:
    x0, y0, x1, y1 = bbox
    return TextBlock(
        text=text,
        raw_text=text,
        polygon=(Point(x0, y0), Point(x1, y0), Point(x1, y1), Point(x0, y1)),
        confidence=None if source_type is SourceType.NATIVE_PDF else 0.9,
        source_type=source_type,
        page_index=0,
        engine_id="test",
        text_block_id=block_id,
    )


def test_native_quality_gate_rejects_invalid_text_layer_geometry():
    result = NativeTextQualityGate().assess(
        (_block("日期", bbox=(-1, 10, 40, 20)),),
        page_width=100,
        page_height=100,
    )

    assert result.passed is False
    assert "bbox_out_of_bounds" in result.reasons


def test_native_quality_gate_accepts_normal_text_layer():
    result = NativeTextQualityGate().assess(
        (_block("交易日期 2026-08-01 余额 100.00"),),
        page_width=100,
        page_height=100,
    )

    assert result.passed is True
    assert result.reasons == ()


def test_hybrid_dedup_prefers_native_block_when_ocr_overlaps_same_text():
    native = _block("余额", block_id="native-1")
    ocr = _block("余额", source_type=SourceType.OCR, block_id="ocr-1")

    result = deduplicate_blocks((native, ocr))

    assert result == (native,)
