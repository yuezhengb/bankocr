from pathlib import Path

from bankocr.domain.coordinates import Point
from bankocr.domain.page import PageClassification, PageKind
from bankocr.domain.run_manifest import RunManifest
from bankocr.domain.text_block import SourceType, TextBlock
from bankocr.ocr.result import OCRPageResult
from bankocr.parser.models import FieldValue, ParserOutcome, TransactionCandidate
from bankocr.parser.temporary_template import TemporaryTemplateConfirmation
from bankocr.pipeline.processor import DocumentPipelineResult, PagePipelineResult
from bankocr.pipeline.run_service import ProjectRunService
from bankocr.storage.project_store import ProjectStore
from bankocr.validation.engine import TransactionValidator, ValidationReport


def _manifest() -> RunManifest:
    return RunManifest(
        app_version="0.1.0",
        project_schema_version="1",
        ocr_engine="test",
        ocr_model_id="test",
        model_sha256="a" * 64,
        execution_provider="cpu",
        preprocess_profile="test",
        parser_version="test",
        template_version="test",
        validation_rules_version="test",
        exporter_version="test",
    )


def _candidate(page_index: int) -> TransactionCandidate:
    return TransactionCandidate(
        page_index=page_index,
        row_index=0,
        parser_id="test:v1",
        fields={"value": FieldValue("raw", "suggested")},
    ).accept()


class _Processor:
    def __init__(self) -> None:
        self.page_indexes = []

    def process(self, source: str | Path, *, dpi: int, page_indexes=None, on_page=None):
        self.page_indexes.append(None if page_indexes is None else tuple(page_indexes))
        pages = tuple(
            PagePipelineResult(
                page_index=index,
                classification=PageClassification(index, PageKind.SCAN_IMAGE),
                ocr_result=None,
                parser_outcome=ParserOutcome.success((_candidate(index),)),
                validation_report=None,
            )
            for index in (page_indexes or (0,))
        )
        if on_page is not None:
            for page in pages:
                on_page(page)
        return DocumentPipelineResult(Path(source).name, pages)


class _TemporaryTemplateProcessor(_Processor):
    def __init__(self) -> None:
        super().__init__()
        self.temporary_templates = []

    def process(
        self,
        source: str | Path,
        *,
        dpi: int,
        page_indexes=None,
        on_page=None,
        temporary_template=None,
    ):
        self.temporary_templates.append(temporary_template)
        return super().process(
            source,
            dpi=dpi,
            page_indexes=page_indexes,
            on_page=on_page,
        )


def test_run_service_records_results_and_resumes_only_pending_pages(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")
    processor = _Processor()
    service = ProjectRunService(store, processor)

    run_id, _ = service.start(project_id, _manifest(), "statement.pdf", dpi=200)
    store.save_page_state(run_id, 1, "pending")
    service.resume(run_id, "statement.pdf", dpi=200)

    assert processor.page_indexes == [None, (1,)]
    assert store.resume_pages(run_id) == ()
    store.close()


def test_run_service_loads_temporary_template_for_the_current_run(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")
    processor = _TemporaryTemplateProcessor()
    service = ProjectRunService(store, processor)
    run_id = store.create_run(project_id, _manifest())
    confirmation = TemporaryTemplateConfirmation(
        run_id=run_id,
        source_page_index=0,
        header_tokens=("date",),
        columns=(
            __import__("bankocr.parser.templates", fromlist=["ColumnDefinition"]).ColumnDefinition(
                "date", 0.0, 1.0
            ),
        ),
        required_fields=("date",),
    )
    store.save_temporary_template(confirmation.to_record())

    service.resume(run_id, "statement.pdf", dpi=200)

    assert processor.temporary_templates == [confirmation.to_record().template]
    store.close()


def test_run_service_can_requeue_review_pages_after_template_confirmation(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")
    processor = _TemporaryTemplateProcessor()
    service = ProjectRunService(store, processor)
    run_id = store.create_run(project_id, _manifest())
    store.save_page_state(run_id, 0, "needs_review", "confirm columns")
    store.set_run_status(run_id, "needs_review")

    service.resume(run_id, "statement.pdf", dpi=200, reprocess_review_pages=True)

    assert processor.page_indexes == [(0,)]
    assert store.get_run_status(run_id) == "completed"
    store.close()


class _FailOnceProcessor(_Processor):
    def __init__(self) -> None:
        super().__init__()
        self.fail = True

    def process(self, source: str | Path, *, dpi: int, page_indexes=None, on_page=None):
        if self.fail:
            self.page_indexes.append(None if page_indexes is None else tuple(page_indexes))
            self.fail = False
            raise RuntimeError("simulated interruption")
        return super().process(source, dpi=dpi, page_indexes=page_indexes, on_page=on_page)


def test_run_service_marks_interrupted_run_failed_and_restarts_uncheckpointed_pages(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")
    processor = _FailOnceProcessor()
    service = ProjectRunService(store, processor)

    try:
        service.start(project_id, _manifest(), "statement.pdf", dpi=200)
    except RuntimeError as exc:
        assert str(exc) == "simulated interruption"
    else:
        raise AssertionError("expected simulated interruption")

    run_id = 1
    assert store.get_run_status(run_id) == "failed"

    service.resume(run_id, "statement.pdf", dpi=200)

    assert processor.page_indexes == [None, None]
    assert store.resume_pages(run_id) == ()
    store.close()


def test_run_service_persists_page_validation_reports(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")
    report = ValidationReport(checked_rows=1, issues=(), final_balances=())

    class ProcessorWithReport(_Processor):
        def process(self, source: str | Path, *, dpi: int, page_indexes=None, on_page=None):
            base = super().process(source, dpi=dpi, page_indexes=page_indexes, on_page=None)
            page = base.pages[0]
            return DocumentPipelineResult(
                base.file,
                (
                    PagePipelineResult(
                        page_index=page.page_index,
                        classification=page.classification,
                        ocr_result=page.ocr_result,
                        parser_outcome=page.parser_outcome,
                        validation_report=report,
                    ),
                ),
            )

    service = ProjectRunService(store, ProcessorWithReport())

    run_id, _ = service.start(project_id, _manifest(), "statement.pdf", dpi=200)

    assert store.load_validation_reports(run_id) == {0: report}
    store.close()


def test_run_service_marks_fail_closed_parser_outcomes_for_review_not_retry(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")

    class FailClosedProcessor(_Processor):
        def process(self, source: str | Path, *, dpi: int, page_indexes=None, on_page=None):
            page = PagePipelineResult(
                page_index=0,
                classification=PageClassification(0, PageKind.SCAN_IMAGE),
                ocr_result=None,
                parser_outcome=ParserOutcome.failed("no trusted template"),
                validation_report=ValidationReport(0, (), ()),
            )
            if on_page is not None:
                on_page(page)
            return DocumentPipelineResult(Path(source).name, (page,))

    run_id, _ = ProjectRunService(store, FailClosedProcessor()).start(
        project_id,
        _manifest(),
        "statement.pdf",
        dpi=200,
    )

    assert store.get_run_status(run_id) == "needs_review"
    assert store.resume_pages(run_id) == ()
    store.close()


def test_run_service_revalidates_persisted_pages_as_one_cross_page_stream(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")

    class CrossPageProcessor(_Processor):
        validator = TransactionValidator()

        def process(self, source: str | Path, *, dpi: int, page_indexes=None, on_page=None):
            indexes = tuple(page_indexes or (0, 1))
            pages = []
            for page_index in indexes:
                amount = "100.00" if page_index == 0 else "-20.00"
                balance = "100.00" if page_index == 0 else "75.00"
                candidate = TransactionCandidate(
                    page_index=page_index,
                    row_index=0,
                    parser_id="test:v1",
                    fields={
                        "transaction_date": FieldValue(
                            f"2026-08-0{page_index + 1}",
                            f"2026-08-0{page_index + 1}",
                        ),
                        "transaction_amount": FieldValue(amount, amount),
                        "balance": FieldValue(balance, balance),
                    },
                ).accept()
                page = PagePipelineResult(
                    page_index=page_index,
                    classification=PageClassification(page_index, PageKind.SCAN_IMAGE),
                    ocr_result=None,
                    parser_outcome=ParserOutcome.success((candidate,)),
                    validation_report=None,
                )
                pages.append(page)
                if on_page is not None:
                    on_page(page)
            return DocumentPipelineResult(Path(source).name, tuple(pages))

    service = ProjectRunService(store, CrossPageProcessor())
    run_id, _ = service.start(project_id, _manifest(), "statement.pdf", dpi=200)

    reports = store.load_validation_reports(run_id)
    assert any(issue.code == "balance_mismatch" for issue in reports[1].issues)
    assert store.get_run_status(run_id) == "needs_review"
    store.close()


def test_run_service_persists_ocr_blocks_for_a_resumed_export(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")
    block = TextBlock(
        text="摘要",
        raw_text="摘要",
        polygon=(Point(1, 1), Point(20, 1), Point(20, 10), Point(1, 10)),
        confidence=0.9,
        source_type=SourceType.OCR,
        page_index=0,
        engine_id="test",
    )

    class ProcessorWithOCR(_Processor):
        def process(self, source: str | Path, *, dpi: int, page_indexes=None, on_page=None):
            base = super().process(source, dpi=dpi, page_indexes=page_indexes, on_page=None)
            page = base.pages[0]
            page = PagePipelineResult(
                page_index=page.page_index,
                classification=page.classification,
                ocr_result=OCRPageResult(0, (block,), "test"),
                parser_outcome=page.parser_outcome,
                validation_report=page.validation_report,
            )
            if on_page is not None:
                on_page(page)
            return DocumentPipelineResult(base.file, (page,))

    service = ProjectRunService(store, ProcessorWithOCR())
    run_id, _ = service.start(project_id, _manifest(), "statement.pdf", dpi=200)

    assert store.load_ocr_blocks(run_id) == {0: (block,)}
    store.close()


def test_run_service_checkpoints_pages_before_processor_interruption(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")

    class StreamingFailProcessor(_Processor):
        def __init__(self) -> None:
            super().__init__()
            self.fail = True

        def process(self, source: str | Path, *, dpi: int, page_indexes=None, on_page=None):
            if self.fail:
                self.page_indexes.append(None if page_indexes is None else tuple(page_indexes))
                self.fail = False
                page = _Processor().process(source, dpi=dpi, page_indexes=(0,)).pages[0]
                if on_page is not None:
                    on_page(page)
                raise RuntimeError("interrupted after page 0")
            return super().process(source, dpi=dpi, page_indexes=page_indexes, on_page=on_page)

    processor = StreamingFailProcessor()
    service = ProjectRunService(store, processor)

    try:
        service.start(project_id, _manifest(), "statement.pdf", dpi=200)
    except RuntimeError as exc:
        assert str(exc) == "interrupted after page 0"
    else:
        raise AssertionError("expected interruption")

    store.save_page_state(1, 1, "pending")
    assert store.load_candidates(1)[0].page_index == 0
    service.resume(1, "statement.pdf", dpi=200)

    assert processor.page_indexes == [None, (1,)]
    store.close()


def test_run_service_rejects_source_changes_when_resuming_a_run(tmp_path: Path) -> None:
    source = tmp_path / "statement.pdf"
    source.write_bytes(b"source-v1")
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", source)
    service = ProjectRunService(store, _Processor())

    run_id, _ = service.start(project_id, _manifest(), source, dpi=200)
    store.save_page_state(run_id, 1, "pending")
    source.write_bytes(b"source-v2")

    try:
        service.resume(run_id, source, dpi=200)
    except ValueError as exc:
        assert "checksum" in str(exc)
    else:
        raise AssertionError("expected source checksum mismatch")
    store.close()


def test_run_service_rejects_manifest_changes_when_resuming_a_run(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")
    service = ProjectRunService(store, _Processor())
    run_id, _ = service.start(project_id, _manifest(), "statement.pdf", dpi=200)
    changed = RunManifest(
        app_version="0.1.1",
        project_schema_version="1",
        ocr_engine="test",
        ocr_model_id="test",
        model_sha256="a" * 64,
        execution_provider="cpu",
        preprocess_profile="test",
        parser_version="test",
        template_version="test",
        validation_rules_version="test",
        exporter_version="test",
    )

    try:
        service.resume(run_id, "statement.pdf", dpi=200, manifest=changed)
    except ValueError as exc:
        assert "manifest" in str(exc)
    else:
        raise AssertionError("expected manifest mismatch")
    store.close()


def test_run_service_seeds_real_pdf_pages_before_processing(tmp_path: Path) -> None:
    import pymupdf

    source = tmp_path / "statement.pdf"
    document = pymupdf.open()
    document.new_page()
    document.new_page()
    document.save(source)
    document.close()

    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", source)
    processor = _FailOnceProcessor()
    service = ProjectRunService(store, processor)

    try:
        service.start(project_id, _manifest(), source, dpi=200)
    except RuntimeError as exc:
        assert str(exc) == "simulated interruption"
    else:
        raise AssertionError("expected simulated interruption")

    assert store.page_statuses(1) == ("pending", "pending")
    service.resume(1, source, dpi=200)

    assert processor.page_indexes == [None, (0, 1)]
    assert store.resume_pages(1) == ()
    store.close()


def test_run_service_does_not_rerun_needs_review_pages(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")
    processor = _Processor()
    service = ProjectRunService(store, processor)

    run_id, _ = service.start(project_id, _manifest(), "statement.pdf", dpi=200)
    store.save_page_state(run_id, 0, "needs_review")
    service.resume(run_id, "statement.pdf", dpi=200)

    assert processor.page_indexes == [None]
    store.close()
