"""Image value objects that keep the PDF coordinate mapping attached."""

from __future__ import annotations

from dataclasses import dataclass

from bankocr.domain.coordinates import CoordinateTransform


@dataclass(frozen=True, slots=True)
class PageImage:
    page_index: int
    width_px: int
    height_px: int
    dpi: int
    payload: object
    transform: CoordinateTransform

    def __post_init__(self) -> None:
        if self.page_index < 0:
            raise ValueError("page_index must be non-negative")
        if self.width_px <= 0 or self.height_px <= 0:
            raise ValueError("image dimensions must be positive")
        if self.dpi <= 0:
            raise ValueError("dpi must be positive")
