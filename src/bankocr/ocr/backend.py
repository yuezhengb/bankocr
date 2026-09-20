"""OCR backend protocol; implementations may use RapidOCR, a fake, or another engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from bankocr.image.types import PageImage
from bankocr.ocr.result import OCRPageResult


@dataclass(frozen=True, slots=True)
class OCROptions:
    languages: tuple[str, ...] = ("ch", "en")
    score_threshold: float = 0.0
    detect_orientation: bool = True
    secondary_variants: tuple[str, ...] = ("original",)
    secondary_upscale: float = 2.0

    def __post_init__(self) -> None:
        if not self.languages:
            raise ValueError("at least one OCR language is required")
        if not 0.0 <= self.score_threshold <= 1.0:
            raise ValueError("score_threshold must be between 0 and 1")
        allowed = {"original", "upscale", "contrast", "adaptive", "line_removed"}
        if not self.secondary_variants or any(item not in allowed for item in self.secondary_variants):
            raise ValueError("secondary_variants contains an unsupported image variant")
        if self.secondary_upscale <= 1.0:
            raise ValueError("secondary_upscale must be greater than 1")


@runtime_checkable
class OCRBackend(Protocol):
    def recognize(self, image: PageImage, options: OCROptions) -> OCRPageResult:
        """Recognize one page without interpreting bank or transaction semantics."""
