"""Page-level routing values shared by PDF preflight and processing state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PageKind(str, Enum):
    NATIVE_TEXT = "native_text"
    SCAN_IMAGE = "scan_image"
    HYBRID = "hybrid"
    PAGE_ERROR = "page_error"
    BLANK = "blank"


@dataclass(frozen=True)
class PageClassification:
    page_index: int
    kind: PageKind
    error: str | None = None

    def __post_init__(self) -> None:
        if self.page_index < 0:
            raise ValueError("page_index must be non-negative")
        if self.kind is PageKind.PAGE_ERROR and not self.error:
            raise ValueError("page error classification requires an error")
        if self.kind is not PageKind.PAGE_ERROR and self.error is not None:
            raise ValueError("only page error classifications may contain an error")
