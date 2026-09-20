"""Deterministic whole-page quarter turns with reversible coordinates."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from bankocr.domain.coordinates import CoordinateTransform


@dataclass(frozen=True, slots=True)
class OrientedImage:
    payload: np.ndarray
    transform: CoordinateTransform
    clockwise_quarter_turns: int


def rotate_quarter_turns(
    payload: np.ndarray,
    transform: CoordinateTransform,
    clockwise_quarter_turns: int,
) -> OrientedImage:
    """Rotate a page clockwise without losing its original PDF mapping.

    Automatic 90-degree guessing is intentionally excluded: a wrong whole-page
    turn silently destroys row association. Callers may set a trusted value
    from PDF metadata, a template, or an explicit operator choice.
    """

    if clockwise_quarter_turns not in (0, 1, 2, 3):
        raise ValueError("clockwise_quarter_turns must be 0, 1, 2, or 3")
    height, width = payload.shape[:2]
    if clockwise_quarter_turns == 0:
        return OrientedImage(payload.copy(), transform, 0)
    if clockwise_quarter_turns == 1:
        rotated = cv2.rotate(payload, cv2.ROTATE_90_CLOCKWISE)
        source_to_output = (0.0, -1.0, float(height), 1.0, 0.0, 0.0)
    elif clockwise_quarter_turns == 2:
        rotated = cv2.rotate(payload, cv2.ROTATE_180)
        source_to_output = (-1.0, 0.0, float(width), 0.0, -1.0, float(height))
    else:
        rotated = cv2.rotate(payload, cv2.ROTATE_90_COUNTERCLOCKWISE)
        source_to_output = (0.0, 1.0, 0.0, -1.0, 0.0, float(width))
    return OrientedImage(
        payload=rotated,
        transform=transform.after_pixel_affine(source_to_output),
        clockwise_quarter_turns=clockwise_quarter_turns,
    )
