import numpy as np

from bankocr.domain.coordinates import CoordinateTransform, Point
from bankocr.domain.text_block import SourceType, TextBlock
from bankocr.image.types import PageImage
from bankocr.ocr.backend import OCROptions
from bankocr.ocr.result import OCRPageResult
from bankocr.ocr.secondary import CellRegion, SecondaryOCR


class _FakeBackend:
    engine_id = "fake-secondary"

    def __init__(self) -> None:
        self.images: list[PageImage] = []

    def recognize(self, image: PageImage, options: OCROptions) -> OCRPageResult:
        self.images.append(image)
        point = image.transform.to_pdf(Point(1, 1))
        block = TextBlock(
            text="cell",
            raw_text="cell",
            polygon=(point, Point(point.x + 2, point.y), Point(point.x + 2, point.y + 4), Point(point.x, point.y + 4)),
            confidence=0.9,
            source_type=SourceType.OCR,
            page_index=image.page_index,
            engine_id=self.engine_id,
        )
        return OCRPageResult(image.page_index, (block,), self.engine_id)


def test_secondary_ocr_crops_cells_and_preserves_pdf_coordinate_mapping() -> None:
    payload = np.zeros((80, 100, 3), dtype=np.uint8)
    image = PageImage(
        page_index=0,
        width_px=100,
        height_px=80,
        dpi=200,
        payload=payload,
        transform=CoordinateTransform.scale(2.0, 2.0, offset_x=10.0, offset_y=20.0),
    )
    backend = _FakeBackend()

    blocks = SecondaryOCR(backend).recognize(
        image,
        (CellRegion(0, "amount", 30.0, 40.0, 70.0, 80.0),),
    )

    assert len(backend.images) == 1
    assert backend.images[0].width_px == 20
    assert backend.images[0].height_px == 20
    assert blocks[0].bbox[0] == 32.0
    assert blocks[0].bbox[1] == 42.0


def test_secondary_ocr_preserves_affine_rotation_when_cropping_a_cell() -> None:
    payload = np.zeros((80, 100, 3), dtype=np.uint8)
    transform = CoordinateTransform(
        1.0,
        1.0,
        matrix=(0.0, 1.0, -1.0, 0.0, 200.0, 10.0),
    )
    image = PageImage(
        page_index=0,
        width_px=100,
        height_px=80,
        dpi=200,
        payload=payload,
        transform=transform,
    )
    backend = _FakeBackend()

    blocks = SecondaryOCR(backend).recognize(
        image,
        (CellRegion(0, "amount", 170.0, 30.0, 190.0, 50.0),),
    )

    crop = backend.images[0]
    assert crop.transform.to_pdf(Point(0.0, 0.0)) == transform.to_pdf(Point(20.0, 10.0))
    assert blocks[0].bbox[0] == crop.transform.to_pdf(Point(1.0, 1.0)).x
