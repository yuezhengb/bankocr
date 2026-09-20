from bankocr.domain.coordinates import CoordinateTransform, Point


def test_coordinate_transform_round_trip_for_scaled_page():
    transform = CoordinateTransform.scale(2.0, 2.0)

    original = Point(100.0, 200.0)
    processed = transform.from_pdf(original)

    assert processed == Point(50.0, 100.0)
    assert transform.to_pdf(processed) == original


def test_coordinate_transform_round_trip_with_translation():
    transform = CoordinateTransform.scale(2.0, 4.0, offset_x=10.0, offset_y=20.0)

    original = Point(110.0, 220.0)
    processed = transform.from_pdf(original)

    assert processed == Point(50.0, 50.0)
    assert transform.to_pdf(processed) == original


def test_coordinate_transform_rejects_non_positive_scale():
    try:
        CoordinateTransform.scale(0.0, 1.0)
    except ValueError as exc:
        assert "scale" in str(exc)
    else:
        raise AssertionError("expected ValueError for zero scale")


def test_after_pixel_affine_accepts_opencv_row_major_matrix() -> None:
    transform = CoordinateTransform.scale(
        2.0,
        3.0,
        offset_x=100.0,
        offset_y=200.0,
    )

    # OpenCV matrix: output_x = source_x + 10, output_y = source_y + 20.
    warped = transform.after_pixel_affine((1.0, 0.0, 10.0, 0.0, 1.0, 20.0))

    mapped = warped.to_pdf(Point(15.0, 27.0))
    assert abs(mapped.x - 110.0) < 1e-9
    assert abs(mapped.y - 221.0) < 1e-9
    round_trip = warped.from_pdf(mapped)
    assert abs(round_trip.x - 15.0) < 1e-9
    assert abs(round_trip.y - 27.0) < 1e-9
