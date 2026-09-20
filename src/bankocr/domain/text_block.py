"""OCR-independent text geometry and field-level provenance models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json

from .coordinates import Point


class SourceType(str, Enum):
    NATIVE_PDF = "native_pdf"
    # Kept as a compatibility value for databases created before v1.1.
    NATIVE_TEXT = "native_text"
    OCR = "ocr"


@dataclass(frozen=True, slots=True)
class TextBlock:
    text: str
    polygon: tuple[Point, ...]
    confidence: float | None
    source_type: SourceType
    page_index: int
    engine_id: str
    raw_text: str
    text_block_id: str = ""

    def __post_init__(self) -> None:
        if not self.polygon:
            raise ValueError("polygon must contain at least one point")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.page_index < 0:
            raise ValueError("page_index must be non-negative")
        if not self.engine_id.strip():
            raise ValueError("engine_id must not be empty")
        if not self.text_block_id:
            payload = json.dumps(
                {
                    "page_index": self.page_index,
                    "source_type": self.source_type.value,
                    "engine_id": self.engine_id,
                    "raw_text": self.raw_text,
                    "polygon": [(point.x, point.y) for point in self.polygon],
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            digest = hashlib.sha256(payload).hexdigest()[:20]
            object.__setattr__(
                self,
                "text_block_id",
                f"p{self.page_index:04d}:{self.source_type.value}:{digest}",
            )

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        xs = tuple(point.x for point in self.polygon)
        ys = tuple(point.y for point in self.polygon)
        return min(xs), min(ys), max(xs), max(ys)


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """A field's exact source geometry and stable originating block ID."""

    page_index: int
    polygon: tuple[Point, ...]
    text_block_id: str

    def __post_init__(self) -> None:
        if self.page_index < 0:
            raise ValueError("page_index must be non-negative")
        if not self.polygon:
            raise ValueError("polygon must contain at least one point")
        if not self.text_block_id.strip():
            raise ValueError("text_block_id must not be empty")

    @classmethod
    def from_block(cls, block: TextBlock) -> "SourceSpan":
        return cls(block.page_index, block.polygon, block.text_block_id)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        xs = tuple(point.x for point in self.polygon)
        ys = tuple(point.y for point in self.polygon)
        return min(xs), min(ys), max(xs), max(ys)
