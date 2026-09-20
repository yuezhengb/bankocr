from pathlib import Path
import pymupdf

from bankocr.domain.coordinates import Point
from bankocr.domain.page import PageClassification, PageKind
from bankocr.domain.run_manifest import RunManifest
from bankocr.domain.text_block import SourceType, TextBlock
from bankocr.ocr.result import OCRPageResult
from bankocr.parser.models import FieldValue, ParserOutcome, TransactionCandidate
from bankocr.pipeline.processor import DocumentPipelineResult, PagePipelineResult
from bankocr.pipeline.run_service import ProjectRunService
from bankocr.storage.project_store import ProjectStore
from bankocr.task.document_queue import PdfTask, PdfTaskExecutor, PdfTaskQueue, ResourcePolicy
from bankocr.validation.engine import ValidationReport


def _manifest() -> RunManifest:
    return RunManifest(
        app_version="test",
        project_schema_version="4",
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


class _Service:
    def __init__(self) -> None:
        self.calls = []

    def start(self, project_id, manifest, source, *, dpi, checkpoint=None):
        if checkpoint is not None:
            checkpoint()
        self.calls.append((project_id, source, dpi))
        return 7, {"pages": 1}


def test_pdf_queue_uses_cpu_first_resource_policy_and_completes_task(tmp_path: Path) -> None:
    source = tmp_path / "input.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(source)
    document.close()
    service = _Service()
    queue = PdfTaskQueue(PdfTaskExecutor(service, policy=ResourcePolicy.low_resource()))
    task_id = queue.submit(PdfTask(source, 1, _manifest()))

    snapshot = queue.run_next()

    assert snapshot is not None
    assert snapshot.status.value == "completed"
    assert service.calls == [(1, source, 150)]


def test_pdf_queue_exports_all_user_artifacts_after_a_persisted_run(tmp_path: Path) -> None:
    source = tmp_path / "input.pdf"
    document = pymupdf.open()
    document.new_page(width=200, height=100)
    document.save(source)
    document.close()
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", source)
    candidate = TransactionCandidate(
        page_index=0,
        row_index=0,
        parser_id="known:v1",
        fields={
            "transaction_date": FieldValue("2026-08-01", "2026-08-01", source_block_indices=(0,)),
            "transaction_amount": FieldValue("10.00", "10.00", source_block_indices=(0,)),
            "balance": FieldValue("10.00", "10.00", source_block_indices=(0,)),
        },
    )
    block = TextBlock(
        text="10.00",
        raw_text="10.00",
        polygon=(Point(10, 10), Point(40, 10), Point(40, 20), Point(10, 20)),
        confidence=0.99,
        source_type=SourceType.OCR,
        page_index=0,
        engine_id="test",
    )

    class Processor:
        def process(self, path, *, dpi, page_indexes=None, on_page=None):
            page = PagePipelineResult(
                page_index=0,
                classification=PageClassification(0, PageKind.SCAN_IMAGE),
                ocr_result=OCRPageResult(0, (block,), "test"),
                parser_outcome=ParserOutcome.success((candidate,)),
                validation_report=ValidationReport(1, (), ()),
            )
            if on_page is not None:
                on_page(page)
            return DocumentPipelineResult(Path(path).name, (page,))

    output = tmp_path / "output"
    queue = PdfTaskQueue(PdfTaskExecutor(ProjectRunService(store, Processor())))
    queue.submit(PdfTask(source, project_id, _manifest(), output_dir=output))

    snapshot = queue.run_next()

    assert snapshot is not None and snapshot.status.value == "completed"
    assert (output / "input.xlsx").is_file()
    assert (output / "input.review.xlsx").is_file()
    assert (output / "input.pdf-layout.xlsx").is_file()
    assert (output / "input.searchable.pdf").is_file()
    assert (output / "input.comparison.pdf").is_file()
    assert (output / "input.summary.json").is_file()
    assert (output / "input.export-manifest.json").is_file()
    store.close()


def test_pdf_queue_updates_only_current_completed_task_result(tmp_path: Path) -> None:
    source = tmp_path / "input.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(source)
    document.close()
    queue = PdfTaskQueue(PdfTaskExecutor(_Service(), policy=ResourcePolicy.low_resource()))
    task_id = queue.submit(PdfTask(source, 1, _manifest()))

    pending_error = None
    try:
        queue.update_result(task_id, {"before": "run"})
    except Exception as error:  # noqa: BLE001 - testing public failure mode
        pending_error = error
    assert pending_error is not None

    snapshot = queue.run_next()
    assert snapshot is not None and snapshot.status.value == "completed"

    updated = queue.update_result(task_id, {"after": "review"})

    assert updated.result == {"after": "review"}
    assert queue.manager.get(task_id).result == {"after": "review"}
