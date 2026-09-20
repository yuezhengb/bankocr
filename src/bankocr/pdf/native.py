"""Extract native PDF text into the same geometry contract as OCR."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from bankocr.domain.coordinates import Point
from bankocr.domain.text_block import SourceType, TextBlock


class NativeTextExtractor:
    engine_id = "pymupdf:native-text"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def extract_page(self, page_index: int) -> tuple[TextBlock, ...]:
        if page_index < 0:
            raise ValueError("page_index must be non-negative")
        try:
            document = pymupdf.open(str(self.path))
        except pymupdf.FileNotFoundError as exc:
            raise FileNotFoundError(self.path) from exc
        try:
            page = document.load_page(page_index)
            blocks: list[TextBlock] = []
            block_number = 0
            for raw_block in page.get_text("dict").get("blocks", ()):
                if raw_block.get("type") != 0:
                    continue
                for line in raw_block.get("lines", ()):
                    for span in line.get("spans", ()):
                        x0, y0, x1, y1 = span["bbox"]
                        raw_text = str(span.get("text", ""))
                        text = raw_text.strip()
                        if not text:
                            continue
                        blocks.append(
                            TextBlock(
                                text=text,
                                raw_text=raw_text,
                                polygon=(Point(float(x0), float(y0)), Point(float(x1), float(y0)), Point(float(x1), float(y1)), Point(float(x0), float(y1))),
                                confidence=None,
                                source_type=SourceType.NATIVE_PDF,
                                page_index=page_index,
                                engine_id=self.engine_id,
                                text_block_id=f"p{page_index:04d}:native:{block_number:06d}",
                            )
                        )
                        block_number += 1
            return tuple(blocks)
        finally:
            document.close()

    def page_size(self, page_index: int) -> tuple[float, float]:
        if page_index < 0:
            raise ValueError("page_index must be non-negative")
        try:
            document = pymupdf.open(str(self.path))
        except pymupdf.FileNotFoundError as exc:
            raise FileNotFoundError(self.path) from exc
        try:
            page = document.load_page(page_index)
            return float(page.mediabox.width), float(page.mediabox.height)
        finally:
            document.close()
