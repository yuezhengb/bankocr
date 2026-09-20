import numpy as np
import pymupdf

from bankocr.domain.coordinates import CoordinateTransform, Point
from bankocr.domain.page import PageKind
from bankocr.image.types import PageImage
from bankocr.ocr.backend import OCROptions
from bankocr.ocr.result import OCRPageResult
from bankocr.parser.templates import ColumnDefinition, TableTemplate
from bankocr.parser.temporary_template import TemporaryTemplateConfirmation
from bankocr.pipeline.processor import DocumentProcessor
from bankocr.pdf.classifier import PageSignals
from bankocr.domain.text_block import SourceType, TextBlock


def _block(text: str, x: float, y: float, *, page_index: int = 0) -> TextBlock:
    return TextBlock(
        text=text,
        raw_text=text,
        polygon=(Point(x, y), Point(x + 15, y), Point(x + 15, y + 6), Point(x, y + 6)),
        confidence=0.95,
        source_type=SourceType.OCR,
        page_index=page_index,
        engine_id="fake",
    )


class _Reader:
    def __init__(self, path: str) -> None:
        self.path = path

    def iter_signals(self):
        yield PageSignals(page_index=0, native_text_chars=0, image_count=1)


class _TwoPageReader:
    def __init__(self, path: str) -> None:
        self.path = path

    def iter_signals(self):
        yield PageSignals(page_index=0, native_text_chars=0, image_count=1)
        yield PageSignals(page_index=1, native_text_chars=0, image_count=1)


class _BlankReader:
    def __init__(self, path: str) -> None:
        self.path = path

    def iter_signals(self):
        yield PageSignals(page_index=0, native_text_chars=0, image_count=0)


class _Renderer:
    def __init__(self, path: str) -> None:
        self.path = path

    def render(self, page_index: int, *, dpi: int) -> PageImage:
        return PageImage(
            page_index=page_index,
            width_px=100,
            height_px=100,
            dpi=dpi,
            payload=np.full((100, 100, 3), 255, dtype=np.uint8),
            transform=CoordinateTransform.scale(1, 1),
        )


class _Backend:
    engine_id = "fake"

    def recognize(self, image: PageImage, options: OCROptions) -> OCRPageResult:
        blocks = (
            _block("日期", 5, 5),
            _block("金额", 30, 5),
            _block("余额", 55, 5),
            _block("2026/08/01", 5, 30),
            _block("10.00", 30, 30),
            _block("10.00", 55, 30),
        )
        return OCRPageResult(0, blocks, self.engine_id)


class _TwoPageBackend:
    engine_id = "fake"

    def recognize(self, image: PageImage, options: OCROptions) -> OCRPageResult:
        page_index = image.page_index
        amount = "100.00" if page_index == 0 else "-20.00"
        balance = "100.00" if page_index == 0 else "75.00"
        blocks = (
            _block("日期", 5, 5, page_index=page_index),
            _block("金额", 30, 5, page_index=page_index),
            _block("余额", 55, 5, page_index=page_index),
            _block(f"2026/08/0{page_index + 1}", 5, 30, page_index=page_index),
            _block(amount, 30, 30, page_index=page_index),
            _block(balance, 55, 30, page_index=page_index),
        )
        return OCRPageResult(page_index, blocks, self.engine_id)


class _FailFirstRenderer(_Renderer):
    def render(self, page_index: int, *, dpi: int) -> PageImage:
        if page_index == 0:
            raise RuntimeError("corrupt page")
        return super().render(page_index, dpi=dpi)


def _template() -> TableTemplate:
    return TableTemplate(
        template_id="pipeline:test:v1",
        version="1",
        header_tokens=("日期", "金额", "余额"),
        columns=(
            ColumnDefinition("accounting_date", 0.0, 0.25),
            ColumnDefinition("transaction_amount", 0.25, 0.55),
            ColumnDefinition("balance", 0.55, 0.8),
        ),
        required_fields=("accounting_date", "transaction_amount", "balance"),
        row_strategy="anchor_date",
    )


def test_document_processor_streams_a_scan_page_through_ocr_parser_and_validator() -> None:
    processor = DocumentProcessor(
        backend=_Backend(),
        templates=(_template(),),
        reader_factory=_Reader,
        renderer_factory=_Renderer,
    )

    result = processor.process("statement.pdf", dpi=200)

    assert len(result.pages) == 1
    page = result.pages[0]
    assert page.classification.kind is PageKind.SCAN_IMAGE
    assert page.ocr_result is not None
    assert len(page.parser_outcome.candidates) == 1
    assert page.validation_report is not None


def test_document_processor_applies_a_confirmed_temporary_template_before_formal_pack() -> None:
    temporary = TemporaryTemplateConfirmation(
        run_id=1,
        source_page_index=0,
        header_tokens=_template().header_tokens,
        columns=_template().columns,
        required_fields=_template().required_fields,
        confirmed_by="reviewer-a",
    ).to_record().template
    processor = DocumentProcessor(
        backend=_Backend(),
        templates=(_template(),),
        reader_factory=_Reader,
        renderer_factory=_Renderer,
    )

    result = processor.process("statement.pdf", dpi=200, temporary_template=temporary)

    assert result.pages[0].parser_outcome.candidates[0].parser_id == temporary.template_id


def test_document_processor_emits_each_completed_page_to_callback() -> None:
    processor = DocumentProcessor(
        backend=_Backend(),
        templates=(_template(),),
        reader_factory=_Reader,
        renderer_factory=_Renderer,
    )
    emitted = []

    result = processor.process("statement.pdf", dpi=200, on_page=emitted.append)

    assert len(emitted) == 1
    assert result.pages == ()
    assert emitted[0].page_index == 0


def test_document_processor_validates_balance_continuity_across_pages() -> None:
    processor = DocumentProcessor(
        backend=_TwoPageBackend(),
        templates=(_template(),),
        reader_factory=_TwoPageReader,
        renderer_factory=_Renderer,
    )

    result = processor.process("statement.pdf", dpi=200)

    assert result.pages[0].validation_report is not None
    assert result.pages[1].validation_report is not None
    assert not any(
        issue.code == "balance_mismatch"
        for issue in result.pages[0].validation_report.issues
    )
    assert any(
        issue.code == "balance_mismatch"
        for issue in result.pages[1].validation_report.issues
    )


def test_document_processor_keeps_processing_after_a_page_local_render_error() -> None:
    processor = DocumentProcessor(
        backend=_TwoPageBackend(),
        templates=(_template(),),
        reader_factory=_TwoPageReader,
        renderer_factory=_FailFirstRenderer,
    )

    result = processor.process("statement.pdf", dpi=200)

    assert len(result.pages) == 2
    assert result.pages[0].classification.kind is PageKind.PAGE_ERROR
    assert len(result.pages[1].parser_outcome.candidates) == 1


def test_document_processor_records_a_blank_page_without_unbound_state() -> None:
    processor = DocumentProcessor(
        backend=_Backend(),
        templates=(_template(),),
        reader_factory=_BlankReader,
        renderer_factory=_Renderer,
    )

    result = processor.process("statement.pdf", dpi=200)

    assert len(result.pages) == 1
    assert result.pages[0].classification.kind is PageKind.BLANK
    assert result.pages[0].parser_outcome.candidates == ()


def test_document_processor_routes_native_text_page_without_ocr(tmp_path) -> None:
    source = tmp_path / "native.pdf"
    document = pymupdf.open()
    page = document.new_page(width=200, height=100)
    native_template = TableTemplate(
        template_id="native:test:v1",
        version="1",
        header_tokens=("DATE", "AMOUNT", "BALANCE"),
        columns=(
            ColumnDefinition("accounting_date", 0.0, 0.25),
            ColumnDefinition("transaction_amount", 0.25, 0.55),
            ColumnDefinition("balance", 0.55, 0.8),
        ),
        required_fields=("accounting_date", "transaction_amount", "balance"),
        row_strategy="anchor_date",
    )
    page.insert_text((5, 15), "DATE AMOUNT BALANCE", fontsize=10)
    page.insert_text((5, 40), "2026/08/01", fontsize=10)
    page.insert_text((60, 50), "10.00", fontsize=10)
    page.insert_text((120, 50), "10.00", fontsize=10)
    document.save(source)
    document.close()

    processor = DocumentProcessor(templates=(native_template,))
    result = processor.process(source)

    assert result.pages[0].classification.kind is PageKind.NATIVE_TEXT
    assert result.pages[0].ocr_result is not None
    assert result.pages[0].ocr_result.engine_id == "pymupdf:native-text"
    assert len(result.pages[0].parser_outcome.candidates) == 1


def test_document_processor_falls_back_to_ocr_when_native_quality_gate_fails(
    monkeypatch,
    tmp_path,
) -> None:
    class NativeReader:
        engine_id = "fake-native"

        def __init__(self, path):
            self.path = path

        def extract_page(self, page_index):
            return (
                TextBlock(
                    text="乱码",
                    raw_text="乱码",
                    polygon=(Point(-2, 10), Point(20, 10), Point(20, 20), Point(-2, 20)),
                    confidence=None,
                    source_type=SourceType.NATIVE_PDF,
                    page_index=page_index,
                    engine_id="fake-native",
                    text_block_id="native-bad",
                ),
            )

        def page_size(self, page_index):
            return 100.0, 100.0

    monkeypatch.setattr("bankocr.pipeline.processor.NativeTextExtractor", NativeReader)

    processor = DocumentProcessor(
        backend=_Backend(),
        templates=(_template(),),
        reader_factory=lambda path: type(
            "NativeSignalsReader",
            (),
            {
                "iter_signals": lambda self: iter(
                    (PageSignals(page_index=0, native_text_chars=20, image_count=0),)
                )
            },
        )(),
        renderer_factory=_Renderer,
    )

    result = processor.process(tmp_path / "native-quality.pdf")

    page = result.pages[0]
    assert page.classification.kind is PageKind.NATIVE_TEXT
    assert page.ocr_result is not None
    assert page.ocr_result.engine_id == "fake"
