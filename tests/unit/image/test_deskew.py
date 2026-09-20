import cv2
import numpy as np
import pytest

from bankocr.domain.coordinates import CoordinateTransform, Point
from bankocr.image.preprocess import PagePreprocessor, PreprocessOptions
from bankocr.image.types import PageImage


def test_preprocessor_reports_and_maps_a_small_skew() -> None:
    canvas = np.full((240, 360, 3), 255, dtype=np.uint8)
    cv2.line(canvas, (30, 120), (330, 140), (0, 0, 0), 3)
    image = PageImage(0, 360, 240, 200, canvas, CoordinateTransform.scale(1.0, 1.0))

    result = PagePreprocessor(
        PreprocessOptions(min_line_length_px=100, deskew_enabled=True)
    ).process(image)

    assert result.deskew_angle_degrees != 0.0
    point = Point(12.0, 34.0)
    round_trip = result.transform.to_pdf(result.transform.from_pdf(point))
    assert round_trip.x == pytest.approx(point.x)
    assert round_trip.y == pytest.approx(point.y)
