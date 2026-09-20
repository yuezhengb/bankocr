"""Targeted cell crops for OCR blocks that cross trusted table boundaries."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import cv2

from bankocr.domain.coordinates import CoordinateTransform, Point
from bankocr.domain.text_block import TextBlock
from bankocr.image.types import PageImage
from bankocr.parser.normalization import normalize_amount, normalize_date

from .backend import OCRBackend, OCROptions


@dataclass(frozen=True, slots=True)
class CellRegion:
    page_index: int
    field_name: str
    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        if self.page_index < 0:
            raise ValueError("page_index must be non-negative")
        if not self.field_name:
            raise ValueError("field_name must not be empty")
        if not self.x0 < self.x1 or not self.y0 < self.y1:
            raise ValueError("cell region must have positive width and height")


class SecondaryOCR:
    def __init__(self, backend: OCRBackend, *, variants: tuple[str, ...] = ("original",)) -> None:
        self.backend = backend
        self.variants = variants

    def recognize(
        self,
        image: PageImage,
        regions: tuple[CellRegion, ...] | list[CellRegion],
        options: OCROptions | None = None,
    ) -> tuple[TextBlock, ...]:
        options = options or OCROptions(secondary_variants=self.variants)
        payload = np.asarray(image.payload)
        if payload.ndim not in (2, 3):
            raise ValueError("page image payload must be a 2D or 3D array")
        blocks = []
        for region in regions:
            if region.page_index != image.page_index:
                raise ValueError("cell region belongs to another page")
            left, top, right, bottom = self._crop_bounds(image, region)
            crop = payload[top:bottom, left:right].copy()
            variants = options.secondary_variants or self.variants
            # Grid recovery may submit hundreds of cells.  Keep the normal
            # pass bounded and reserve expensive image variants for targeted
            # crops; callers can still request variants explicitly for a
            # small region set.
            if len(regions) > 32:
                variants = ("original",)
            variant_results: list[tuple[float, tuple[TextBlock, ...]]] = []
            for variant in variants:
                variant_payload, factor = _variant(crop, variant, options.secondary_upscale)
                crop_height, crop_width = variant_payload.shape[:2]
                crop_image = PageImage(
                    page_index=image.page_index,
                    width_px=crop_width,
                    height_px=crop_height,
                    dpi=image.dpi,
                    payload=variant_payload,
                    transform=image.transform.crop(left, top).resize(factor),
                )
                result = self.backend.recognize(crop_image, options)
                variant_results.append((_variant_score(region.field_name, result.blocks), result.blocks))
            if variant_results:
                blocks.extend(max(variant_results, key=lambda item: item[0])[1])
        return tuple(blocks)

    @staticmethod
    def _crop_bounds(image: PageImage, region: CellRegion) -> tuple[int, int, int, int]:
        corners = (
            Point(region.x0, region.y0),
            Point(region.x1, region.y0),
            Point(region.x1, region.y1),
            Point(region.x0, region.y1),
        )
        pixels = tuple(image.transform.from_pdf(corner) for corner in corners)
        pixel_left = min(point.x for point in pixels)
        pixel_top = min(point.y for point in pixels)
        pixel_right = max(point.x for point in pixels)
        pixel_bottom = max(point.y for point in pixels)
        left = max(0, min(image.width_px - 1, math.floor(pixel_left)))
        top = max(0, min(image.height_px - 1, math.floor(pixel_top)))
        right = max(left + 1, min(image.width_px, math.ceil(pixel_right)))
        bottom = max(top + 1, min(image.height_px, math.ceil(pixel_bottom)))
        return left, top, right, bottom


def _variant(payload: np.ndarray, name: str, upscale: float) -> tuple[np.ndarray, float]:
    if name == "original":
        return payload, 1.0
    if name == "upscale":
        factor = float(upscale)
        height, width = payload.shape[:2]
        return cv2.resize(payload, (max(1, round(width * factor)), max(1, round(height * factor))), interpolation=cv2.INTER_CUBIC), factor
    gray = payload if payload.ndim == 2 else cv2.cvtColor(payload, cv2.COLOR_BGR2GRAY)
    if name == "contrast":
        return cv2.convertScaleAbs(gray, alpha=1.6, beta=-30), 1.0
    if name == "adaptive":
        return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11), 1.0
    if name == "line_removed":
        horizontal = cv2.morphologyEx(gray, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, gray.shape[1] // 8), 1)))
        vertical = cv2.morphologyEx(gray, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(3, gray.shape[0] // 8))))
        return cv2.subtract(gray, cv2.max(horizontal, vertical)), 1.0
    raise ValueError(f"unsupported secondary OCR variant: {name}")


def _variant_score(field_name: str, blocks: tuple[TextBlock, ...]) -> float:
    score = sum(block.confidence or 0.0 for block in blocks)
    text = " ".join(
        block.text
        for block in sorted(blocks, key=lambda item: (item.bbox[1], item.bbox[0]))
    )
    field = field_name.casefold()
    if "date" in field:
        score += 10.0 if normalize_date(text) is not None else 0.25 * any(character.isdigit() for character in text)
    if any(token in field for token in ("amount", "balance")):
        score += 10.0 if normalize_amount(text) is not None else 0.25 * any(character.isdigit() for character in text)
    return score
