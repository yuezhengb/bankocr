"""Page-level preflight classification."""

from __future__ import annotations

from dataclasses import dataclass

from bankocr.domain.page import PageClassification, PageKind


@dataclass(frozen=True, slots=True)
class PageSignals:
    page_index: int
    native_text_chars: int
    image_count: int
    error: str | None = None
    page_width: float | None = None
    page_height: float | None = None
    rotation: int = 0
    content_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if self.page_index < 0:
            raise ValueError("page_index must be non-negative")
        if self.native_text_chars < 0:
            raise ValueError("native_text_chars must be non-negative")
        if self.image_count < 0:
            raise ValueError("image_count must be non-negative")
        if self.page_width is not None and self.page_width <= 0:
            raise ValueError("page_width must be positive")
        if self.page_height is not None and self.page_height <= 0:
            raise ValueError("page_height must be positive")
        if self.rotation % 90 != 0:
            raise ValueError("rotation must be a multiple of 90 degrees")


class PageClassifier:
    def classify(self, signals: PageSignals) -> PageClassification:
        if signals.error:
            return PageClassification(
                page_index=signals.page_index,
                kind=PageKind.PAGE_ERROR,
                error=signals.error,
            )
        if signals.native_text_chars and signals.image_count:
            kind = PageKind.HYBRID
        elif signals.native_text_chars:
            kind = PageKind.NATIVE_TEXT
        elif signals.image_count:
            kind = PageKind.SCAN_IMAGE
        else:
            kind = PageKind.BLANK
        return PageClassification(page_index=signals.page_index, kind=kind)
