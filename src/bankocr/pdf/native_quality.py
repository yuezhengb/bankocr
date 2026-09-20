"""Quality gate and overlap handling for native PDF text layers."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from collections.abc import Iterable

from bankocr.domain.text_block import SourceType, TextBlock


@dataclass(frozen=True, slots=True)
class NativeTextQualityResult:
    passed: bool
    reasons: tuple[str, ...] = ()


class NativeTextQualityGate:
    """Reject suspicious text layers before they become parser input."""

    def __init__(
        self,
        *,
        min_text_chars: int = 4,
        bbox_tolerance: float = 0.0,
        max_height_ratio: float = 0.25,
    ) -> None:
        if min_text_chars < 0:
            raise ValueError("min_text_chars must be non-negative")
        if bbox_tolerance < 0:
            raise ValueError("bbox_tolerance must be non-negative")
        if not 0.0 < max_height_ratio <= 1.0:
            raise ValueError("max_height_ratio must be between 0 and 1")
        self.min_text_chars = min_text_chars
        self.bbox_tolerance = bbox_tolerance
        self.max_height_ratio = max_height_ratio

    def assess(
        self,
        blocks: Iterable[TextBlock],
        *,
        page_width: float,
        page_height: float,
    ) -> NativeTextQualityResult:
        if page_width <= 0 or page_height <= 0:
            raise ValueError("page dimensions must be positive")
        values = tuple(blocks)
        reasons: list[str] = []
        if not values:
            reasons.append("empty_text_layer")
        printable_text = 0
        for block in values:
            text = unicodedata.normalize("NFKC", block.text)
            printable_text += len("".join(text.split()))
            if any(
                ord(character) < 32 and character not in "\t\n\r"
                or character == "\ufffd"
                for character in text
            ):
                reasons.append("invalid_characters")
            x0, y0, x1, y1 = block.bbox
            tolerance = self.bbox_tolerance
            if (
                x0 < -tolerance
                or y0 < -tolerance
                or x1 > page_width + tolerance
                or y1 > page_height + tolerance
                or x1 <= x0
                or y1 <= y0
            ):
                reasons.append("bbox_out_of_bounds")
            if y1 - y0 > page_height * self.max_height_ratio:
                reasons.append("bbox_height_anomaly")
        if printable_text < self.min_text_chars:
            reasons.append("text_layer_too_sparse")
        unique_reasons = tuple(dict.fromkeys(reasons))
        return NativeTextQualityResult(not unique_reasons, unique_reasons)


def deduplicate_blocks(
    blocks: Iterable[TextBlock],
    *,
    overlap_threshold: float = 0.75,
) -> tuple[TextBlock, ...]:
    """Remove native/OCR duplicates while retaining the native evidence block."""

    if not 0.0 < overlap_threshold <= 1.0:
        raise ValueError("overlap_threshold must be between 0 and 1")
    kept: list[TextBlock] = []
    for candidate in blocks:
        duplicate_index: int | None = None
        for index, existing in enumerate(kept):
            if candidate.page_index != existing.page_index:
                continue
            if _normalize(candidate.text) != _normalize(existing.text):
                continue
            if _intersection_over_union(candidate.bbox, existing.bbox) < overlap_threshold:
                continue
            if _is_native(candidate) and not _is_native(existing):
                duplicate_index = index
            elif _is_native(existing) or not _is_native(candidate):
                duplicate_index = -1
            else:
                duplicate_index = -1
            break
        if duplicate_index is None:
            kept.append(candidate)
        elif duplicate_index >= 0:
            kept[duplicate_index] = candidate
    return tuple(kept)


def _is_native(block: TextBlock) -> bool:
    return block.source_type in {SourceType.NATIVE_PDF, SourceType.NATIVE_TEXT}


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()


def _intersection_over_union(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    ix0, iy0 = max(left[0], right[0]), max(left[1], right[1])
    ix1, iy1 = min(left[2], right[2]), min(left[3], right[3])
    intersection = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    union = left_area + right_area - intersection
    return 0.0 if union <= 0 else intersection / union
