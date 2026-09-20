import pytest

from bankocr.domain.page import PageKind
from bankocr.pdf.classifier import PageClassifier, PageSignals


@pytest.mark.parametrize(
    ("signals", "expected"),
    [
        (PageSignals(page_index=0, native_text_chars=120, image_count=0), PageKind.NATIVE_TEXT),
        (PageSignals(page_index=1, native_text_chars=0, image_count=1), PageKind.SCAN_IMAGE),
        (PageSignals(page_index=2, native_text_chars=120, image_count=1), PageKind.HYBRID),
        (PageSignals(page_index=3, native_text_chars=0, image_count=0), PageKind.BLANK),
    ],
)
def test_page_classifier_routes_page_by_local_content_signals(signals, expected):
    assert PageClassifier().classify(signals).kind is expected


def test_page_classifier_keeps_unreadable_page_as_page_error():
    signals = PageSignals(
        page_index=9,
        native_text_chars=0,
        image_count=0,
        error="page cannot be rendered",
    )

    result = PageClassifier().classify(signals)

    assert result.kind is PageKind.PAGE_ERROR
    assert result.error == "page cannot be rendered"
