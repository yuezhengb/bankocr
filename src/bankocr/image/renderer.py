"""Streaming PDF page rendering with a reversible coordinate transform."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pymupdf

from bankocr.domain.coordinates import CoordinateTransform
from .types import PageImage


class PdfRenderer:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def render(self, page_index: int, *, dpi: int = 300) -> PageImage:
        if page_index < 0:
            raise ValueError("page_index must be non-negative")
        if dpi <= 0:
            raise ValueError("dpi must be positive")
        document = pymupdf.open(str(self.path))
        try:
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(dpi=dpi, alpha=False)
            channels = pixmap.n
            array = np.frombuffer(pixmap.samples, dtype=np.uint8)
            array = array.reshape(pixmap.height, pixmap.width, channels)[..., :3].copy()
            scale_x = page.rect.width / pixmap.width
            scale_y = page.rect.height / pixmap.height
            if page.rotation in (0, 360):
                transform = CoordinateTransform.scale(scale_x, scale_y)
            else:
                rotation = page.derotation_matrix
                transform = CoordinateTransform(
                    1.0,
                    1.0,
                    matrix=(
                        rotation.a * scale_x,
                        rotation.b * scale_x,
                        rotation.c * scale_y,
                        rotation.d * scale_y,
                        rotation.e,
                        rotation.f,
                    ),
                )
            return PageImage(
                page_index=page_index,
                width_px=pixmap.width,
                height_px=pixmap.height,
                dpi=dpi,
                payload=array,
                transform=transform,
            )
        finally:
            document.close()
