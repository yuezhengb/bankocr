"""Keep OCR pixels and table-structure pixels as separate processing channels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np

from bankocr.domain.coordinates import CoordinateTransform, Point
from .orientation import rotate_quarter_turns
from .types import PageImage


Orientation = Literal["horizontal", "vertical"]


@dataclass(frozen=True, slots=True)
class PreprocessOptions:
    """Deterministic parameters for the first table-line preprocessing profile."""

    adaptive_block_size: int = 31
    adaptive_c: int = 11
    line_gap_px: int = 7
    min_line_length_px: int = 50
    line_kernel_divisor: int = 30
    deskew_enabled: bool = True
    max_skew_degrees: float = 5.0
    clockwise_quarter_turns: int = 0

    def __post_init__(self) -> None:
        if self.adaptive_block_size < 3 or self.adaptive_block_size % 2 == 0:
            raise ValueError("adaptive_block_size must be an odd integer >= 3")
        if self.line_gap_px <= 0:
            raise ValueError("line_gap_px must be positive")
        if self.min_line_length_px <= 0:
            raise ValueError("min_line_length_px must be positive")
        if self.line_kernel_divisor <= 0:
            raise ValueError("line_kernel_divisor must be positive")
        if self.max_skew_degrees <= 0 or self.max_skew_degrees > 45:
            raise ValueError("max_skew_degrees must be in (0, 45]")
        if self.clockwise_quarter_turns not in (0, 1, 2, 3):
            raise ValueError("clockwise_quarter_turns must be 0, 1, 2, or 3")


@dataclass(frozen=True, slots=True)
class LineSegment:
    """A line recovered in processed-pixel coordinates."""

    x1: int
    y1: int
    x2: int
    y2: int
    orientation: Orientation

    @property
    def length(self) -> int:
        if self.orientation == "horizontal":
            return abs(self.x2 - self.x1)
        return abs(self.y2 - self.y1)


@dataclass(frozen=True, slots=True)
class PreprocessedPage:
    """The OCR image and structure mask produced from one rendered page."""

    page_index: int
    transform: CoordinateTransform
    ocr_image: np.ndarray
    structure_image: np.ndarray
    horizontal_lines: tuple[LineSegment, ...]
    vertical_lines: tuple[LineSegment, ...]
    deskew_angle_degrees: float = 0.0
    clockwise_quarter_turns: int = 0

    @property
    def horizontal_boundaries_pdf(self) -> tuple[float, ...]:
        return tuple(
            sorted(
                {
                    self.transform.to_pdf(Point(0.0, line.y1)).y
                    for line in self.horizontal_lines
                }
            )
        )


class PagePreprocessor:
    """Build independent OCR and table-structure channels for one page."""

    def __init__(self, options: PreprocessOptions | None = None) -> None:
        self.options = options or PreprocessOptions()

    def process(self, image: PageImage) -> PreprocessedPage:
        ocr_image = self._as_rgb_uint8(image.payload)
        oriented = rotate_quarter_turns(
            ocr_image,
            image.transform,
            self.options.clockwise_quarter_turns,
        )
        ocr_image = oriented.payload
        transform = oriented.transform
        gray = cv2.cvtColor(ocr_image, cv2.COLOR_RGB2GRAY)
        binary = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            self.options.adaptive_block_size,
            self.options.adaptive_c,
        )

        applied_angle = 0.0
        if self.options.deskew_enabled:
            estimated = self._estimate_skew(binary)
            if abs(estimated) >= 0.2 and abs(estimated) <= self.options.max_skew_degrees:
                applied_angle = -estimated
                center = (ocr_image.shape[1] / 2.0, ocr_image.shape[0] / 2.0)
                matrix = cv2.getRotationMatrix2D(center, applied_angle, 1.0)
                ocr_image = cv2.warpAffine(
                    ocr_image,
                    matrix,
                    (ocr_image.shape[1], ocr_image.shape[0]),
                    flags=cv2.INTER_LINEAR,
                    borderValue=(255, 255, 255),
                )
                transform = transform.after_pixel_affine(tuple(float(value) for value in matrix.flat))
                gray = cv2.cvtColor(ocr_image, cv2.COLOR_RGB2GRAY)
                binary = cv2.adaptiveThreshold(
                    gray,
                    255,
                    cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                    cv2.THRESH_BINARY_INV,
                    self.options.adaptive_block_size,
                    self.options.adaptive_c,
                )

        horizontal_mask = self._extract_lines(binary, "horizontal")
        vertical_mask = self._extract_lines(binary, "vertical")
        structure_image = cv2.bitwise_or(horizontal_mask, vertical_mask)

        return PreprocessedPage(
            page_index=image.page_index,
            transform=transform,
            ocr_image=ocr_image,
            structure_image=structure_image,
            horizontal_lines=self._segments(horizontal_mask, "horizontal"),
            vertical_lines=self._segments(vertical_mask, "vertical"),
            deskew_angle_degrees=applied_angle,
            clockwise_quarter_turns=oriented.clockwise_quarter_turns,
        )

    def _estimate_skew(self, binary: np.ndarray) -> float:
        lines = cv2.HoughLinesP(
            binary,
            1,
            np.pi / 180.0,
            threshold=max(20, self.options.min_line_length_px // 2),
            minLineLength=self.options.min_line_length_px,
            maxLineGap=self.options.line_gap_px * 2,
        )
        angles: list[float] = []
        if lines is None:
            return 0.0
        for line in np.asarray(lines).reshape(-1, 4):
            x1, y1, x2, y2 = map(float, line)
            angle = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
            if angle > 45.0:
                angle -= 90.0
            elif angle < -45.0:
                angle += 90.0
            if abs(angle) <= self.options.max_skew_degrees:
                angles.append(angle)
        return float(np.median(angles)) if angles else 0.0

    def _extract_lines(self, binary: np.ndarray, orientation: Orientation) -> np.ndarray:
        if orientation == "horizontal":
            length = max(3, binary.shape[1] // self.options.line_kernel_divisor)
            bridge = np.ones((1, self.options.line_gap_px * 2 + 1), dtype=np.uint8)
            kernel = np.ones((1, length), dtype=np.uint8)
        else:
            length = max(3, binary.shape[0] // self.options.line_kernel_divisor)
            bridge = np.ones((self.options.line_gap_px * 2 + 1, 1), dtype=np.uint8)
            kernel = np.ones((length, 1), dtype=np.uint8)

        bridged = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, bridge)
        return cv2.morphologyEx(bridged, cv2.MORPH_OPEN, kernel)

    def _segments(self, mask: np.ndarray, orientation: Orientation) -> tuple[LineSegment, ...]:
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        segments: list[LineSegment] = []
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            line_length = width if orientation == "horizontal" else height
            thickness = height if orientation == "horizontal" else width
            if line_length < self.options.min_line_length_px:
                continue
            if line_length < max(5, thickness * 5):
                continue
            if orientation == "horizontal":
                center_y = y + height // 2
                segments.append(LineSegment(x, center_y, x + width - 1, center_y, orientation))
            else:
                center_x = x + width // 2
                segments.append(LineSegment(center_x, y, center_x, y + height - 1, orientation))

        if orientation == "horizontal":
            segments.sort(key=lambda line: (line.y1, line.x1))
        else:
            segments.sort(key=lambda line: (line.x1, line.y1))
        return tuple(segments)

    @staticmethod
    def _as_rgb_uint8(payload: object) -> np.ndarray:
        array = np.asarray(payload)
        if array.dtype != np.uint8:
            raise TypeError("page image payload must use uint8 pixels")
        if array.ndim == 2:
            return cv2.cvtColor(array, cv2.COLOR_GRAY2RGB)
        if array.ndim == 3 and array.shape[2] == 3:
            return array.copy()
        raise ValueError("page image payload must be grayscale or RGB")
