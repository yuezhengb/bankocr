import cv2
import numpy as np
import pytest

from bankocr.domain.coordinates import CoordinateTransform
from bankocr.image.preprocess import PagePreprocessor, PreprocessOptions
from bankocr.image.types import PageImage


def _page_image(payload: np.ndarray) -> PageImage:
    height, width = payload.shape[:2]
    return PageImage(
        page_index=0,
        width_px=width,
        height_px=height,
        dpi=200,
        payload=payload,
        transform=CoordinateTransform.scale(1.0, 1.0),
    )


def test_preprocessor_keeps_ocr_channel_separate_and_recovers_dotted_table_lines() -> None:
    canvas = np.full((300, 500, 3), 255, dtype=np.uint8)
    cv2.line(canvas, (40, 60), (460, 60), (0, 0, 0), 2)
    cv2.line(canvas, (40, 180), (460, 180), (0, 0, 0), 2)
    for x in range(40, 461, 12):
        cv2.line(canvas, (x, 60), (x + 6, 60), (255, 255, 255), 2)
    cv2.line(canvas, (80, 60), (80, 250), (0, 0, 0), 2)
    cv2.line(canvas, (420, 60), (420, 250), (0, 0, 0), 2)
    cv2.putText(canvas, "2026 100.00", (105, 130), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    original = canvas.copy()

    processed = PagePreprocessor(
        PreprocessOptions(
            min_line_length_px=100,
            line_gap_px=10,
            adaptive_block_size=31,
        )
    ).process(_page_image(canvas))

    assert np.array_equal(canvas, original)
    assert processed.ocr_image.shape == canvas.shape
    assert processed.ocr_image.dtype == np.uint8
    assert processed.structure_image.shape == canvas.shape[:2]
    assert processed.transform == CoordinateTransform.scale(1.0, 1.0)
    assert 60.0 in processed.horizontal_boundaries_pdf
    assert 180.0 in processed.horizontal_boundaries_pdf
    assert set(np.unique(processed.structure_image)).issubset({0, 255})
    assert any(abs(line.y1 - 60) <= 3 for line in processed.horizontal_lines)
    assert any(abs(line.y1 - 180) <= 3 for line in processed.horizontal_lines)
    assert any(abs(line.x1 - 80) <= 3 for line in processed.vertical_lines)
    assert any(abs(line.x1 - 420) <= 3 for line in processed.vertical_lines)


def test_preprocessor_does_not_report_lines_on_blank_page() -> None:
    canvas = np.full((240, 320, 3), 255, dtype=np.uint8)

    processed = PagePreprocessor().process(_page_image(canvas))

    assert processed.horizontal_lines == ()
    assert processed.vertical_lines == ()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"adaptive_block_size": 2},
        {"adaptive_block_size": 4},
        {"line_gap_px": 0},
        {"min_line_length_px": 0},
    ],
)
def test_preprocess_options_reject_invalid_morphology_parameters(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        PreprocessOptions(**kwargs)
