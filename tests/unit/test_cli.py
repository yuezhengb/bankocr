from pathlib import Path
import json
import pymupdf

from bankocr import cli
from bankocr.domain.page import PageClassification, PageKind
from bankocr.parser.models import FieldValue, ParserOutcome, TransactionCandidate
from bankocr.pipeline.processor import DocumentPipelineResult, PagePipelineResult
from bankocr.validation.engine import IssueSeverity, ValidationIssue, ValidationReport


def _write_pdf(path: Path) -> None:
    document = pymupdf.open()
    document.new_page()
    document.save(path)
    document.close()


def test_cli_passes_validation_reports_and_source_file_to_excel_export(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "statement.pdf"
    _write_pdf(source)
    output_dir = tmp_path / "output"
    candidate = TransactionCandidate(
        page_index=0,
        row_index=0,
        parser_id="test:v1",
        fields={"amount": FieldValue("1.00", "1.00")},
    )
    report = ValidationReport(
        checked_rows=1,
        issues=(
            ValidationIssue(
                code="test_issue",
                message="needs review",
                severity=IssueSeverity.ERROR,
                row_index=0,
            ),
        ),
        final_balances=(None,),
    )
    result = DocumentPipelineResult(
        file=source.name,
        pages=(
            PagePipelineResult(
                page_index=0,
                classification=PageClassification(0, PageKind.NATIVE_TEXT),
                ocr_result=None,
                parser_outcome=ParserOutcome.success((candidate,)),
                validation_report=report,
            ),
        ),
    )

    class FakeProcessor:
        def __init__(self, *, backend) -> None:
            self.backend = backend

        def process(self, path, *, dpi):
            assert path == source
            assert dpi == 200
            return result

    excel_calls = []

    def fake_excel_export(self, candidates, output, **kwargs):
        excel_calls.append((tuple(candidates), output, kwargs))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"xlsx")
        return output

    def fake_searchable_export(self, source, output, blocks_by_page):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"pdf")
        return output

    def fake_comparison_export(
        self,
        source,
        output,
        candidates,
        blocks_by_page,
        **kwargs,
    ):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"comparison-pdf")
        return output

    monkeypatch.setattr(cli, "DocumentProcessor", FakeProcessor)
    monkeypatch.setattr(cli.ExcelExporter, "export", fake_excel_export)
    monkeypatch.setattr(cli.SearchablePdfExporter, "export", fake_searchable_export)
    monkeypatch.setattr(cli.ComparisonPdfExporter, "export", fake_comparison_export)

    assert cli.main([str(source), "--output-dir", str(output_dir)]) == 0

    assert len(excel_calls) == 1
    candidates, output, kwargs = excel_calls[0]
    assert candidates == (candidate,)
    assert output == output_dir / "statement.xlsx"
    assert kwargs["source_file"] == source.name
    assert kwargs["validation_reports"] == {0: report}
    assert (output_dir / "statement.review.xlsx").is_file()
    assert (output_dir / "statement.pdf-layout.xlsx").is_file()
    assert (output_dir / "statement.comparison.pdf").is_file()
    summary = json.loads((output_dir / "statement.summary.json").read_text(encoding="utf-8"))
    assert summary["outputs"]["review_excel"] == "statement.review.xlsx"
    assert summary["outputs"]["pdf_layout_excel"] == "statement.pdf-layout.xlsx"
    assert summary["outputs"]["comparison_pdf"] == "statement.comparison.pdf"
    assert summary["outputs"]["export_manifest"] == "statement.export-manifest.json"
    manifest = json.loads(
        (output_dir / "statement.export-manifest.json").read_text(encoding="utf-8")
    )
    assert set(manifest["outputs"]) == {
        "excel",
        "review_excel",
        "pdf_layout_excel",
        "searchable_pdf",
        "comparison_pdf",
    }


def test_cli_project_mode_persists_run_and_can_reuse_saved_candidates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "statement.pdf"
    _write_pdf(source)
    output_dir = tmp_path / "output"
    project_db = tmp_path / "project.sqlite3"
    candidate = TransactionCandidate(
        page_index=0,
        row_index=0,
        parser_id="test:v1",
        fields={"amount": FieldValue("1.00", "1.00")},
    )
    result = DocumentPipelineResult(
        file=source.name,
        pages=(
            PagePipelineResult(
                page_index=0,
                classification=PageClassification(0, PageKind.NATIVE_TEXT),
                ocr_result=None,
                parser_outcome=ParserOutcome.success((candidate,)),
                validation_report=ValidationReport(checked_rows=1, issues=(), final_balances=()),
            ),
        ),
    )

    class FakePack:
        fingerprint = "a" * 64

    class FakeBackend:
        engine_id = "test-engine"
        model_pack = FakePack()

    class FakeProcessor:
        def __init__(self, *, backend) -> None:
            self.backend = backend
            self.calls = []

        def process(self, path, *, dpi, page_indexes=None, on_page=None):
            self.calls.append(None if page_indexes is None else tuple(page_indexes))
            if page_indexes == ():
                return DocumentPipelineResult(source.name, ())
            if on_page is not None:
                on_page(result.pages[0])
            return result

    processors = []

    def make_processor(*, backend):
        processor = FakeProcessor(backend=backend)
        processors.append(processor)
        return processor

    monkeypatch.setattr(cli, "RapidOCRBackend", lambda: FakeBackend())
    monkeypatch.setattr(cli, "DocumentProcessor", make_processor)

    def fake_searchable_export(self, source, output, blocks_by_page):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"pdf")
        return output

    def fake_comparison_export(
        self,
        source,
        output,
        candidates,
        blocks_by_page,
        **kwargs,
    ):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"comparison-pdf")
        return output

    monkeypatch.setattr(cli.SearchablePdfExporter, "export", fake_searchable_export)
    monkeypatch.setattr(cli.ComparisonPdfExporter, "export", fake_comparison_export)

    assert cli.main(
        [
            str(source),
            "--output-dir",
            str(output_dir),
            "--project-db",
            str(project_db),
        ]
    ) == 0

    from bankocr.storage.project_store import ProjectStore

    with ProjectStore(project_db) as store:
        assert store.load_candidates(1) == (candidate,)
        assert store.get_run_status(1) == "completed"

    summary = json.loads((output_dir / "statement.summary.json").read_text(encoding="utf-8"))
    assert summary["run_id"] == 1
    assert summary["outputs"]["export_manifest"] == "statement.export-manifest.json"
    assert processors[0].calls == [None]
