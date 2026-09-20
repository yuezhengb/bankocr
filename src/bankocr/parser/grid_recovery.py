"""Secondary OCR recovery for grid cells whose primary OCR crosses columns."""

from __future__ import annotations

from dataclasses import dataclass

from bankocr.image.types import PageImage
from bankocr.ocr.secondary import CellRegion, SecondaryOCR

from .grid import GridTableParser
from .models import ParserOutcome
from .templates import TableTemplate


@dataclass(frozen=True, slots=True)
class GridRecoveryOptions:
    cell_margin: float = 1.5
    header_band_index: int = 0

    def __post_init__(self) -> None:
        if self.cell_margin < 0:
            raise ValueError("cell_margin must not be negative")
        if self.header_band_index < 0:
            raise ValueError("header_band_index must not be negative")


class GridCellRecovery:
    def __init__(self, secondary_ocr: SecondaryOCR, options: GridRecoveryOptions | None = None) -> None:
        self.secondary_ocr = secondary_ocr
        self.options = options or GridRecoveryOptions()

    def parse(
        self,
        image: PageImage,
        template: TableTemplate,
        *,
        page_width: float,
        horizontal_boundaries: tuple[float, ...],
    ) -> ParserOutcome:
        if template.row_strategy != "grid":
            raise ValueError("grid recovery requires a grid template")
        if len(horizontal_boundaries) < 2:
            return ParserOutcome.failed("grid recovery requires at least one row band")

        regions: list[CellRegion] = []
        for band_index, (top, bottom) in enumerate(
            zip(horizontal_boundaries, horizontal_boundaries[1:])
        ):
            if band_index == self.options.header_band_index:
                continue
            for column in template.columns:
                x0 = column.left_ratio * page_width + self.options.cell_margin
                x1 = column.right_ratio * page_width - self.options.cell_margin
                y0 = top + self.options.cell_margin
                y1 = bottom - self.options.cell_margin
                if x0 >= x1 or y0 >= y1:
                    continue
                regions.append(CellRegion(image.page_index, column.name, x0, y0, x1, y1))

        blocks = self.secondary_ocr.recognize(image, tuple(regions))
        return GridTableParser(template, page_width=page_width).parse(
            blocks,
            horizontal_boundaries=horizontal_boundaries,
        )
