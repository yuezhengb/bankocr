import numpy as np

from bankocr.domain.coordinates import CoordinateTransform, Point
from bankocr.domain.text_block import SourceType, TextBlock
from bankocr.image.types import PageImage
from bankocr.ocr.backend import OCROptions
from bankocr.ocr.result import OCRPageResult
from bankocr.ocr.secondary import SecondaryOCR
from bankocr.parser.grid_recovery import GridCellRecovery
from bankocr.parser.models import ParserOutcomeStatus
from bankocr.parser.templates import ColumnDefinition, TableTemplate


class _FakeCellBackend:
    engine_id = "fake-cell"

    def recognize(self, image: PageImage, options: OCROptions) -> OCRPageResult:
        origin = image.transform.to_pdf(Point(1.0, 1.0))
        block = TextBlock(
            text="cell",
            raw_text="cell",
            polygon=(origin, Point(origin.x + 2, origin.y), Point(origin.x + 2, origin.y + 3), Point(origin.x, origin.y + 3)),
            confidence=0.9,
            source_type=SourceType.OCR,
            page_index=image.page_index,
            engine_id=self.engine_id,
        )
        return OCRPageResult(image.page_index, (block,), self.engine_id)


def test_grid_recovery_reocrizes_each_data_cell_and_reparses_structure_bands() -> None:
    template = TableTemplate(
        template_id="grid:recovery:v1",
        version="1",
        header_tokens=("日期", "金额"),
        columns=(ColumnDefinition("date", 0.0, 0.5), ColumnDefinition("amount", 0.5, 1.0)),
        required_fields=("date", "amount"),
        row_strategy="grid",
    )
    image = PageImage(
        page_index=0,
        width_px=100,
        height_px=50,
        dpi=200,
        payload=np.zeros((50, 100, 3), dtype=np.uint8),
        transform=CoordinateTransform.scale(1.0, 1.0),
    )

    outcome = GridCellRecovery(SecondaryOCR(_FakeCellBackend())).parse(
        image,
        template,
        page_width=100.0,
        horizontal_boundaries=(0.0, 20.0, 40.0),
    )

    assert outcome.status is ParserOutcomeStatus.NEEDS_REVIEW
    assert len(outcome.candidates) == 1
    assert outcome.candidates[0].field("date").raw_text == "cell"
