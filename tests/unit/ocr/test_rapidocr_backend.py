from types import SimpleNamespace

import numpy as np

from bankocr.domain.coordinates import CoordinateTransform, Point
from bankocr.image.types import PageImage
from bankocr.ocr.backend import OCROptions
from bankocr.ocr.rapidocr_backend import RapidOCRBackend


class FakeRapidOCR:
    def __call__(self, payload):
        assert payload.shape == (20, 30, 3)
        return SimpleNamespace(
            boxes=np.array(
                [[[20.0, 40.0], [40.0, 40.0], [40.0, 60.0], [20.0, 60.0]]],
                dtype=np.float32,
            ),
            txts=("50000.00",),
            scores=(0.98,),
        )


def test_rapidocr_backend_maps_pixel_boxes_back_to_pdf_coordinates():
    image = PageImage(
        page_index=2,
        width_px=30,
        height_px=20,
        dpi=144,
        payload=np.zeros((20, 30, 3), dtype=np.uint8),
        transform=CoordinateTransform.scale(0.5, 0.5),
    )

    result = RapidOCRBackend(engine=FakeRapidOCR()).recognize(image, OCROptions())

    block = result.blocks[0]
    assert block.text == "50000.00"
    assert block.raw_text == "50000.00"
    assert block.confidence == 0.98
    assert block.polygon[0] == Point(10.0, 20.0)
    assert block.polygon[2] == Point(20.0, 30.0)
    assert block.engine_id.startswith("rapidocr:")


class _ConfigurableRapidOCR:
    def __init__(self) -> None:
        self.calls = []

    def __call__(self, payload, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            boxes=np.array(
                [
                    [[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0]],
                    [[5.0, 5.0], [9.0, 5.0], [9.0, 9.0], [5.0, 9.0]],
                ],
                dtype=np.float32,
            ),
            txts=("keep", "drop"),
            scores=(0.95, 0.40),
        )


def test_rapidocr_backend_applies_threshold_and_orientation_options() -> None:
    engine = _ConfigurableRapidOCR()
    image = PageImage(
        page_index=0,
        width_px=10,
        height_px=10,
        dpi=200,
        payload=np.zeros((10, 10, 3), dtype=np.uint8),
        transform=CoordinateTransform.scale(1.0, 1.0),
    )

    result = RapidOCRBackend(engine=engine).recognize(
        image,
        OCROptions(score_threshold=0.80, detect_orientation=False),
    )

    assert [block.text for block in result.blocks] == ["keep"]
    assert engine.calls == [{"use_cls": False, "text_score": 0.80}]

