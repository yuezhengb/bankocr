import numpy as np
import pytest

from bankocr.domain.coordinates import CoordinateTransform, Point
from bankocr.image.orientation import rotate_quarter_turns


def test_clockwise_quarter_turn_preserves_pdf_coordinates() -> None:
    payload = np.zeros((100, 200, 3), dtype=np.uint8)
    transform = CoordinateTransform.scale(2.0, 3.0)

    rotated = rotate_quarter_turns(payload, transform, 1)

    assert rotated.payload.shape == (200, 100, 3)
    # Source (20, 30) becomes output (70, 20) after a clockwise turn.
    mapped = rotated.transform.to_pdf(Point(70.0, 20.0))
    assert mapped.x == pytest.approx(40.0)
    assert mapped.y == pytest.approx(90.0)


@pytest.mark.parametrize("turns", [-1, 4])
def test_quarter_turn_rejects_out_of_range_values(turns: int) -> None:
    payload = np.zeros((10, 20, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        rotate_quarter_turns(payload, CoordinateTransform.scale(1.0, 1.0), turns)
