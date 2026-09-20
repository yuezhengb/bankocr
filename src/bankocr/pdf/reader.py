"""Streaming PDF page inspection backed by PyMuPDF."""

from __future__ import annotations

from collections.abc import Iterator
import hashlib
import json
from pathlib import Path

import pymupdf

from .classifier import PageSignals


class PdfReader:
    """Read one PDF page at a time and release the document after iteration."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def iter_signals(self) -> Iterator[PageSignals]:
        try:
            document = pymupdf.open(str(self.path))
        except pymupdf.FileNotFoundError as exc:
            raise FileNotFoundError(self.path) from exc
        try:
            for page_index in range(document.page_count):
                try:
                    page = document.load_page(page_index)
                    text = page.get_text("text") or ""
                    images = page.get_images(full=True)
                    yield PageSignals(
                        page_index=page_index,
                        native_text_chars=len(text.strip()),
                        image_count=len(images),
                        page_width=float(page.rect.width),
                        page_height=float(page.rect.height),
                        rotation=int(page.rotation),
                        content_fingerprint=_content_fingerprint(
                            text, images, page.rect.width, page.rect.height, page.rotation
                        ),
                    )
                except Exception as exc:  # page-local failure must not abort the document
                    yield PageSignals(
                        page_index=page_index,
                        native_text_chars=0,
                        image_count=0,
                        error=f"{type(exc).__name__}: {exc}",
                    )
        finally:
            document.close()


def _content_fingerprint(
    text: str,
    images: tuple[object, ...] | list[object],
    width: float,
    height: float,
    rotation: int,
) -> str:
    payload = json.dumps(
        {
            "text": text,
            "images": [str(item) for item in images],
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
