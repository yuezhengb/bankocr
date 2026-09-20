import numpy as np

from bankocr.domain.coordinates import CoordinateTransform, Point
from bankocr.domain.text_block import SourceType, TextBlock
from bankocr.image.types import PageImage
from bankocr.parser.models import FieldValue, ParserOutcome, TransactionCandidate
from bankocr.pipeline.secondary_recovery import recover_validation_fields
from bankocr.validation.engine import IssueSeverity, ValidationIssue, ValidationReport


def _block(text: str) -> TextBlock:
    return TextBlock(
        text=text,
        raw_text=text,
        polygon=(Point(10, 10), Point(50, 10), Point(50, 20), Point(10, 20)),
        confidence=0.95,
        source_type=SourceType.OCR,
        page_index=0,
        engine_id="fake",
    )


class _Secondary:
    def recognize(self, _image, _regions):
        return (_block("11,954.40"),)


def test_targeted_secondary_ocr_preserves_raw_and_updates_only_suggestion() -> None:
    candidate = TransactionCandidate(
        page_index=0,
        row_index=2,
        parser_id="known:v1",
        fields={
            "online_balance": FieldValue(
                "11,954,40",
                "11,954,40",
                source_block_indices=(0,),
            )
        },
    )
    report = ValidationReport(
        checked_rows=1,
        issues=(
            ValidationIssue(
                "invalid_amount",
                "invalid",
                IssueSeverity.ERROR,
                row_index=2,
                field_name="online_balance",
            ),
        ),
        final_balances=(None,),
    )
    image = PageImage(
        page_index=0,
        width_px=100,
        height_px=100,
        dpi=200,
        payload=np.zeros((100, 100, 3), dtype=np.uint8),
        transform=CoordinateTransform.scale(1, 1),
    )

    recovered = recover_validation_fields(
        image,
        (_block("11,954,40"),),
        ParserOutcome.success((candidate,)),
        report,
        _Secondary(),
    )

    field = recovered.candidates[0].field("online_balance")
    assert field.raw_text == "11,954,40"
    assert field.secondary_text == "11,954.40"
    assert field.suggested_text == "11954.40"
    assert field.final_text is None
