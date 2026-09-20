"""Deterministic OCR benchmark metrics."""

from __future__ import annotations

from dataclasses import dataclass

from bankocr.ocr.result import OCRPageResult


@dataclass(frozen=True, slots=True)
class OCRTextTruth:
    page_index: int
    text: str

    def __post_init__(self) -> None:
        if self.page_index < 0:
            raise ValueError("page_index must be non-negative")


@dataclass(frozen=True, slots=True)
class OCRBenchmarkReport:
    page_count: int
    exact_page_matches: int
    character_accuracy: float
    predicted_block_count: int


class OCRBenchmarkEvaluator:
    def evaluate(
        self,
        *,
        results: tuple[OCRPageResult, ...],
        truths: tuple[OCRTextTruth, ...],
    ) -> OCRBenchmarkReport:
        truth_by_page: dict[int, OCRTextTruth] = {}
        for truth in truths:
            if truth.page_index in truth_by_page:
                raise ValueError(f"duplicate ground truth page: {truth.page_index}")
            truth_by_page[truth.page_index] = truth
        result_by_page = {result.page_index: result for result in results}
        if set(result_by_page) != set(truth_by_page):
            raise ValueError("OCR results and ground truth must cover the same pages")

        distance_total = 0
        expected_total = 0
        exact = 0
        block_count = 0
        for page_index, truth in truth_by_page.items():
            result_text = "".join(block.text for block in result_by_page[page_index].blocks)
            distance = _levenshtein_distance(result_text, truth.text)
            distance_total += distance
            expected_total += len(truth.text)
            block_count += len(result_by_page[page_index].blocks)
            if result_text == truth.text:
                exact += 1
        accuracy = max(0.0, 1.0 - distance_total / max(expected_total, 1))
        return OCRBenchmarkReport(
            page_count=len(truth_by_page),
            exact_page_matches=exact,
            character_accuracy=accuracy,
            predicted_block_count=block_count,
        )


def _levenshtein_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]
