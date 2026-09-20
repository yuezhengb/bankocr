from bankocr.benchmark.evaluator import OCRBenchmarkEvaluator, OCRTextTruth
from bankocr.domain.coordinates import Point
from bankocr.domain.text_block import SourceType, TextBlock
from bankocr.ocr.result import OCRPageResult


def _result(page_index: int, *texts: str) -> OCRPageResult:
    blocks = tuple(
        TextBlock(
            text=text,
            raw_text=text,
            polygon=(Point(0, 0), Point(1, 0), Point(1, 1), Point(0, 1)),
            confidence=0.99,
            source_type=SourceType.OCR,
            page_index=page_index,
            engine_id="fake",
        )
        for text in texts
    )
    return OCRPageResult(page_index=page_index, blocks=blocks, engine_id="fake")


def test_benchmark_reports_exact_pages_and_character_accuracy():
    report = OCRBenchmarkEvaluator().evaluate(
        results=(_result(0, "ABC"), _result(1, "12")),
        truths=(OCRTextTruth(0, "ABC"), OCRTextTruth(1, "123")),
    )

    assert report.page_count == 2
    assert report.exact_page_matches == 1
    assert report.character_accuracy == 5 / 6
    assert report.predicted_block_count == 2


def test_benchmark_rejects_duplicate_ground_truth_page_numbers():
    try:
        OCRBenchmarkEvaluator().evaluate(
            results=(_result(0, "ABC"),),
            truths=(OCRTextTruth(0, "ABC"), OCRTextTruth(0, "ABC")),
        )
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("expected duplicate truth validation")
