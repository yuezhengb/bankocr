"""Overlay invisible OCR text while keeping the original PDF untouched."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from pathlib import Path

import pymupdf

from bankocr.domain.text_block import TextBlock


class SearchablePdfExporter:
    def __init__(self, font_file: str | Path | None = None) -> None:
        self.font_file = _resolve_cjk_font(font_file)

    def export(
        self,
        source: str | Path,
        output: str | Path,
        blocks_by_page: Mapping[int, tuple[TextBlock, ...]],
    ) -> Path:
        source_path = Path(source).resolve()
        output_path = Path(output).resolve()
        if source_path == output_path:
            raise ValueError("searchable PDF output must not overwrite the source PDF")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        document = pymupdf.open(str(source_path))
        try:
            add_searchable_text_layer(document, blocks_by_page, self.font_file)
            document.save(str(output_path), garbage=3, deflate=True)
        finally:
            document.close()
        return output_path


def add_searchable_text_layer(
    document: pymupdf.Document,
    blocks_by_page: Mapping[int, Sequence[TextBlock]],
    font_file: Path | None,
) -> None:
    """Add invisible OCR text to an open PDF without changing its page artwork."""

    for page_index, blocks in blocks_by_page.items():
        if page_index < 0 or page_index >= document.page_count:
            raise ValueError(f"page index out of range: {page_index}")
        page = document.load_page(page_index)
        for block in blocks:
            x0, y0, x1, y1 = block.bbox
            if x1 <= x0 or y1 <= y0:
                continue
            rect = pymupdf.Rect(x0, y0, x1, y1)
            font_kwargs = _font_kwargs(block.text, font_file)
            page.insert_textbox(
                rect,
                block.text,
                fontsize=max(3.0, min(12.0, (y1 - y0) * 0.5)),
                render_mode=3,
                overlay=True,
                **font_kwargs,
            )


def _resolve_cjk_font(font_file: str | Path | None) -> Path | None:
    if font_file is not None:
        path = Path(font_file).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"CJK font file does not exist: {path}")
        return path
    configured = os.environ.get("BANKOCR_CJK_FONT")
    candidates = [Path(configured).expanduser() if configured else None]
    candidates.extend(
        Path(path)
        for path in (
            r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\simhei.ttf",
            r"C:\Windows\Fonts\NotoSansSC-VF.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        )
    )
    return next((path.resolve() for path in candidates if path is not None and path.is_file()), None)


def _font_kwargs(text: str, font_file: Path | None) -> dict[str, str]:
    if any(ord(character) > 255 for character in text):
        if font_file is None:
            raise RuntimeError(
                "searchable PDF contains non-Latin text but no CJK font is available; "
                "pass font_file or set BANKOCR_CJK_FONT"
            )
        return {"fontname": "bankocr-cjk", "fontfile": str(font_file)}
    return {"fontname": "helv"}
