from bankocr.domain.page import PageClassification, PageKind


def test_page_classification_keeps_page_error_local():
    classification = PageClassification(
        page_index=9,
        kind=PageKind.PAGE_ERROR,
        error="cannot render page",
    )

    assert classification.page_index == 9
    assert classification.kind is PageKind.PAGE_ERROR
    assert classification.error == "cannot render page"
