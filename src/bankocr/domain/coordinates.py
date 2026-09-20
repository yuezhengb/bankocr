"""Dependency-free coordinate primitives used by every downstream pipeline stage."""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class CoordinateTransform:
    """Map processed-image coordinates to and from PDF coordinates.

    Axis-aligned scale/translation is the common path; an optional affine
    matrix keeps rotated-page mapping independent of image-library details.
    """

    scale_x: float
    scale_y: float
    offset_x: float = 0.0
    offset_y: float = 0.0
    matrix: tuple[float, float, float, float, float, float] | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("scale_x", self.scale_x),
            ("scale_y", self.scale_y),
            ("offset_x", self.offset_x),
            ("offset_y", self.offset_y),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.scale_x <= 0 or self.scale_y <= 0:
            raise ValueError("scale values must be greater than zero")
        if self.matrix is not None:
            if len(self.matrix) != 6 or not all(math.isfinite(value) for value in self.matrix):
                raise ValueError("matrix must contain six finite values")
            a, b, c, d, _, _ = self.matrix
            if abs(a * d - b * c) <= 1e-12:
                raise ValueError("matrix must be invertible")

    @classmethod
    def scale(
        cls,
        scale_x: float,
        scale_y: float,
        *,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
    ) -> CoordinateTransform:
        return cls(scale_x, scale_y, offset_x, offset_y)

    def from_pdf(self, point: Point) -> Point:
        if self.matrix is not None:
            a, b, c, d, e, f = self.matrix
            determinant = a * d - b * c
            translated_x = point.x - e
            translated_y = point.y - f
            return Point(
                (d * translated_x - c * translated_y) / determinant,
                (-b * translated_x + a * translated_y) / determinant,
            )
        return Point(
            (point.x - self.offset_x) / self.scale_x,
            (point.y - self.offset_y) / self.scale_y,
        )

    def to_pdf(self, point: Point) -> Point:
        if self.matrix is not None:
            a, b, c, d, e, f = self.matrix
            return Point(
                a * point.x + c * point.y + e,
                b * point.x + d * point.y + f,
            )
        return Point(
            point.x * self.scale_x + self.offset_x,
            point.y * self.scale_y + self.offset_y,
        )

    def crop(self, left: float, top: float) -> CoordinateTransform:
        """Return a transform whose origin is ``(left, top)`` in this image."""

        if not math.isfinite(left) or not math.isfinite(top):
            raise ValueError("crop offsets must be finite")
        if self.matrix is None:
            return CoordinateTransform(
                self.scale_x,
                self.scale_y,
                offset_x=self.offset_x + left * self.scale_x,
                offset_y=self.offset_y + top * self.scale_y,
            )
        a, b, c, d, e, f = self.matrix
        return CoordinateTransform(
            self.scale_x,
            self.scale_y,
            matrix=(a, b, c, d, e + a * left + c * top, f + b * left + d * top),
        )

    def resize(self, factor: float) -> CoordinateTransform:
        """Return a transform for an image resized by ``factor`` pixels."""

        if not math.isfinite(factor) or factor <= 0:
            raise ValueError("resize factor must be greater than zero")
        if self.matrix is None:
            return CoordinateTransform(
                self.scale_x / factor,
                self.scale_y / factor,
                offset_x=self.offset_x,
                offset_y=self.offset_y,
            )
        a, b, c, d, e, f = self.matrix
        return CoordinateTransform(
            self.scale_x / factor,
            self.scale_y / factor,
            matrix=(a / factor, b / factor, c / factor, d / factor, e, f),
        )

    def after_pixel_affine(
        self,
        source_to_output: tuple[float, float, float, float, float, float],
    ) -> CoordinateTransform:
        """Map OpenCV affine-warp output pixels back to PDF space.

        ``source_to_output`` follows ``cv2.warpAffine`` row-major order:
        ``(m00, m01, m02, m10, m11, m12)``.
        """

        a, c, e, b, d, f = source_to_output
        determinant = a * d - b * c
        if abs(determinant) <= 1e-12:
            raise ValueError("pixel affine must be invertible")
        ia, ib = d / determinant, -b / determinant
        ic, id_ = -c / determinant, a / determinant
        ie = -(ia * e + ic * f)
        iff = -(ib * e + id_ * f)
        if self.matrix is None:
            aa, ac, ae = self.scale_x, 0.0, self.offset_x
            ab, ad, af = 0.0, self.scale_y, self.offset_y
        else:
            aa, ab, ac, ad, ae, af = self.matrix
        return CoordinateTransform(
            1.0,
            1.0,
            matrix=(
                aa * ia + ac * ib,
                ab * ia + ad * ib,
                aa * ic + ac * id_,
                ab * ic + ad * id_,
                aa * ie + ac * iff + ae,
                ab * ie + ad * iff + af,
            ),
        )
