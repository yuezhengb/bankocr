from bankocr.domain.coordinates import CoordinateTransform, Point
from bankocr.domain.text_block import SourceType, TextBlock
from bankocr.image.types import PageImage
from bankocr.ocr.backend import OCRBackend, OCROptions
from bankocr.ocr.result import OCRPageResult


def _block(page_index: int, text: str = "余额"):
    return TextBlock(
        text=text,
        raw_text=text,
        polygon=(
            Point(0.0, 0.0),
            Point(10.0, 0.0),
            Point(10.0, 10.0),
            Point(0.0, 10.0),
        ),
        confidence=0.99,
        source_type=SourceType.OCR,
        page_index=page_index,
        engine_id="fake",
    )


class FakeOCRBackend:
    def recognize(self, image: PageImage, options: OCROptions) -> OCRPageResult:
        return OCRPageResult(
            page_index=image.page_index,
            blocks=(_block(image.page_index),),
            engine_id="fake-ocr",
        )


def test_ocr_backend_contract_is_engine_independent():
    backend = FakeOCRBackend()
    image = PageImage(
        page_index=4,
        width_px=100,
        height_px=200,
        dpi=300,
        payload=object(),
        transform=CoordinateTransform.scale(2.0, 2.0),
    )

    result = backend.recognize(image, OCROptions())

    assert isinstance(backend, OCRBackend)
    assert result.page_index == 4
    assert result.blocks[0].text == "余额"
    assert result.engine_id == "fake-ocr"


def test_ocr_page_result_rejects_block_from_another_page():
    try:
        OCRPageResult(
            page_index=4,
            blocks=(_block(5),),
            engine_id="fake-ocr",
        )
    except ValueError as exc:
        assert "page_index" in str(exc)
    else:
        raise AssertionError("expected page consistency validation")
