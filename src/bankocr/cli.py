"""Command-line entry point for offline PDF processing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bankocr.domain.run_manifest import RunManifest
from bankocr.export.comparison_pdf import ComparisonPdfExporter
from bankocr.export.excel import ExcelExporter
from bankocr.export.manifest import ExportManifest, count_unresolved
from bankocr.export.pdf_layout import PdfLayoutExcelExporter
from bankocr.export.review import ReviewExcelExporter
from bankocr.export.searchable_pdf import SearchablePdfExporter
from bankocr.ocr.model_pack import ModelPack
from bankocr.ocr.rapidocr_backend import RapidOCRBackend
from bankocr.pipeline.processor import DocumentProcessor
from bankocr.pipeline.run_service import ProjectRunService
from bankocr.pdf.preflight import PdfPreflightError, run_preflight
from bankocr.storage.project_store import ProjectStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Process one bank statement PDF offline")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--model-dir", type=Path, help="explicit local RapidOCR model pack")
    parser.add_argument("--model-manifest", type=Path, help="SHA-256 manifest for --model-dir")
    parser.add_argument(
        "--template-dir",
        type=Path,
        help="local declarative template pack directory (defaults to templates/known)",
    )
    parser.add_argument(
        "--project-db",
        type=Path,
        help="SQLite project database for page checkpoints and resumable runs",
    )
    parser.add_argument(
        "--project-name",
        default=None,
        help="project name when creating a new SQLite run",
    )
    parser.add_argument(
        "--resume-run",
        type=int,
        help="resume an existing run id from --project-db",
    )
    parser.add_argument(
        "--reprocess-review-pages",
        action="store_true",
        help="requeue PAGE_REVIEW pages before resuming (use after confirming a Temporary Template)",
    )
    parser.add_argument(
        "--font-file",
        type=Path,
        help="local CJK font used for searchable PDF text layers",
    )
    args = parser.parse_args(argv)
    if not args.input.is_file():
        parser.error(f"input PDF does not exist: {args.input}")
    if args.dpi <= 0:
        parser.error("--dpi must be positive")
    if args.model_manifest and not args.model_dir:
        parser.error("--model-manifest requires --model-dir")
    if args.resume_run is not None and not args.project_db:
        parser.error("--resume-run requires --project-db")
    if args.reprocess_review_pages and args.resume_run is None:
        parser.error("--reprocess-review-pages requires --resume-run")
    output_paths = (
        args.output_dir / f"{args.input.stem}.xlsx",
        args.output_dir / f"{args.input.stem}.review.xlsx",
        args.output_dir / f"{args.input.stem}.pdf-layout.xlsx",
        args.output_dir / f"{args.input.stem}.searchable.pdf",
        args.output_dir / f"{args.input.stem}.comparison.pdf",
        args.output_dir / f"{args.input.stem}.export-manifest.json",
        args.output_dir / f"{args.input.stem}.summary.json",
    )
    try:
        preflight = run_preflight(
            args.input,
            output_dir=args.output_dir,
            output_paths=output_paths,
            minimum_free_bytes=max(args.input.stat().st_size * 3, 64 * 1024 * 1024),
        )
    except PdfPreflightError as exc:
        parser.error(str(exc))
    project_db = args.project_db
    auto_project_db = False
    if project_db is None and preflight.page_count > 20:
        project_db = args.output_dir / f"{args.input.stem}.bankocr.sqlite3"
        auto_project_db = True
    if args.model_dir:
        model_pack = (
            ModelPack.from_manifest(args.model_dir, args.model_manifest)
            if args.model_manifest
            else ModelPack.from_directory(args.model_dir)
        )
        backend = RapidOCRBackend(model_pack=model_pack)
    else:
        backend = RapidOCRBackend()
    store: ProjectStore | None = None
    run_id: int | None = None
    run_manifest: RunManifest | None = None
    try:
        processor = (
            DocumentProcessor(backend=backend, template_dir=args.template_dir)
            if args.template_dir is not None
            else DocumentProcessor(backend=backend)
        )
        if project_db is None:
            result = processor.process(args.input, dpi=args.dpi)
            candidates = tuple(
                candidate
                for page in result.pages
                for candidate in page.parser_outcome.candidates
            )
            validation_reports = {
                page.page_index: page.validation_report
                for page in result.pages
                if page.validation_report is not None
            }
            page_errors = {
                page.page_index: page.parser_outcome.reason
                or page.classification.error
                or "page processing failed"
                for page in result.pages
                if page.parser_outcome.reason is not None or page.classification.error is not None
            }
            blocks_by_page = {
                page.page_index: page.ocr_result.blocks
                for page in result.pages
                if page.ocr_result is not None
            }
            run_metadata = {
                "source_sha256": preflight.source_sha256,
                "ocr_engine": backend.engine_id,
                "template_fingerprint": getattr(processor, "template_fingerprint", ""),
                "validation_rules_fingerprint": getattr(
                    processor, "validation_rules_fingerprint", ""
                ),
            }
        else:
            store = ProjectStore(project_db)
            service = ProjectRunService(store, processor)
            if args.resume_run is None:
                project_id = store.create_project(
                    args.project_name or args.input.stem,
                    args.input,
                )
                run_manifest = _run_manifest(backend, processor)
                run_id, result = service.start(
                    project_id,
                    run_manifest,
                    args.input,
                    dpi=args.dpi,
                )
            else:
                run_id = args.resume_run
                run_manifest = _run_manifest(backend, processor)
                result = service.resume(
                    args.resume_run,
                    args.input,
                    dpi=args.dpi,
                    manifest=run_manifest,
                    reprocess_review_pages=args.reprocess_review_pages,
                )
            candidates = store.load_candidates(run_id)
            validation_reports = store.load_validation_reports(run_id)
            page_errors = store.page_errors(run_id)
            blocks_by_page = store.load_ocr_blocks(run_id)
            run_metadata = run_manifest.to_dict() if run_manifest is not None else {}
            run_metadata = {
                **run_metadata,
                "source_sha256": store.get_run_source_sha256(run_id),
            }

        args.output_dir.mkdir(parents=True, exist_ok=True)
        excel = ExcelExporter().export(
            candidates,
            args.output_dir / f"{args.input.stem}.xlsx",
            source_file=result.file,
            validation_reports=validation_reports,
            metadata=run_metadata,
            blocks_by_page=blocks_by_page,
        )
        review = ReviewExcelExporter().export(
            candidates,
            validation_reports,
            args.output_dir / f"{args.input.stem}.review.xlsx",
            source_file=result.file,
            page_errors=page_errors,
        )
        pdf_layout_excel = PdfLayoutExcelExporter().export(
            args.input,
            args.output_dir / f"{args.input.stem}.pdf-layout.xlsx",
            candidates,
        )
        searchable = SearchablePdfExporter(font_file=args.font_file).export(
            args.input,
            args.output_dir / f"{args.input.stem}.searchable.pdf",
            blocks_by_page,
        )
        comparison = ComparisonPdfExporter(font_file=args.font_file).export(
            args.input,
            args.output_dir / f"{args.input.stem}.comparison.pdf",
            candidates,
            blocks_by_page,
            validation_reports=validation_reports,
        )
        export_manifest = ExportManifest.create(
            run_id=run_id,
            source_sha256=preflight.source_sha256,
            unresolved_count=count_unresolved(candidates, validation_reports, page_errors),
            outputs={
                "excel": excel,
                "review_excel": review,
                "pdf_layout_excel": pdf_layout_excel,
                "searchable_pdf": searchable,
                "comparison_pdf": comparison,
            },
        )
        export_manifest_path = export_manifest.write(
            args.output_dir / f"{args.input.stem}.export-manifest.json"
        )
        page_summary = _page_summary(result, candidates, validation_reports, store, run_id)
        summary = {
            "file": result.file,
            "run_id": run_id,
            "run_status": store.get_run_status(run_id) if store is not None else None,
            "outputs": {
                "excel": f"{args.input.stem}.xlsx",
                "review_excel": f"{args.input.stem}.review.xlsx",
                "pdf_layout_excel": f"{args.input.stem}.pdf-layout.xlsx",
                "searchable_pdf": f"{args.input.stem}.searchable.pdf",
                "comparison_pdf": f"{args.input.stem}.comparison.pdf",
                "export_manifest": export_manifest_path.name,
                **(
                    {"project_db": project_db.name}
                    if auto_project_db and project_db is not None
                    else {}
                ),
            },
            "preflight": {
                "page_count": preflight.page_count,
                "blank_pages": list(preflight.blank_pages),
                "repeated_pages": [list(group) for group in preflight.repeated_pages],
                "rotated_pages": list(preflight.rotated_pages),
                "warnings": list(preflight.warnings),
            },
            "pages": page_summary,
        }
        (args.output_dir / f"{args.input.stem}.summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return 0
    finally:
        if store is not None:
            store.close()


def _run_manifest(backend: RapidOCRBackend, processor: DocumentProcessor | None = None) -> RunManifest:
    model_pack = backend.model_pack
    if model_pack is None:
        raise RuntimeError("a local model pack is required for a persisted run manifest")
    return RunManifest(
        app_version="0.1.0",
        project_schema_version=str(ProjectStore.SCHEMA_VERSION),
        ocr_engine=backend.engine_id,
        ocr_model_id="PP-OCRv6-small",
        model_sha256=model_pack.fingerprint,
        execution_provider="CPUExecutionProvider",
        preprocess_profile="default-v1",
        parser_version="parser-v1",
        template_version="templates-v1",
        validation_rules_version="validation-v1",
        exporter_version="export-v1",
        template_fingerprint=getattr(processor, "template_fingerprint", ""),
        validation_rules_fingerprint=(
            getattr(processor, "validation_rules_fingerprint", "")
        ),
    )


def _page_summary(result, candidates, validation_reports, store, run_id):
    if result.pages:
        return [
            {
                "page_index": page.page_index,
                "kind": page.classification.kind.value,
                "parser_status": page.parser_outcome.status.value,
                "candidate_count": len(page.parser_outcome.candidates),
                "validation_issue_count": len(page.validation_report.issues)
                if page.validation_report
                else 0,
                "validation_status": page.validation_report.status.value
                if page.validation_report is not None and page.validation_report.status is not None
                else "unknown",
                "risk_score": page.validation_report.risk_score
                if page.validation_report is not None
                else None,
            }
            for page in result.pages
        ]
    if store is None or run_id is None:
        return []
    counts: dict[int, int] = {}
    for candidate in candidates:
        counts[candidate.page_index] = counts.get(candidate.page_index, 0) + 1
    return [
        {
            "page_index": page_index,
            "kind": "persisted",
            "parser_status": status,
            "candidate_count": counts.get(page_index, 0),
            "validation_issue_count": len(
                validation_reports.get(page_index).issues
                if page_index in validation_reports
                else ()
            ),
            "validation_status": validation_reports.get(page_index).status.value
            if page_index in validation_reports and validation_reports[page_index].status is not None
            else "unknown",
            "risk_score": validation_reports.get(page_index).risk_score
            if page_index in validation_reports
            else None,
        }
        for page_index, status in store.page_states(run_id)
    ]
if __name__ == "__main__":
    raise SystemExit(main())
