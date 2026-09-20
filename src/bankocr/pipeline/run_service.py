"""Persisted run lifecycle with page-level resume support."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, Protocol, Iterable

from bankocr.domain.page import PageKind
from bankocr.domain.run_manifest import RunManifest
from bankocr.parser.models import ParserOutcomeStatus
from bankocr.parser.templates import TableTemplate
from bankocr.pipeline.processor import DocumentPipelineResult, PagePipelineResult
from bankocr.pdf.reader import PdfReader
from bankocr.storage.project_store import ProjectStore


class _Processor(Protocol):
    def process(
        self,
        source: str | Path,
        *,
        dpi: int,
        page_indexes: Iterable[int] | None = None,
        on_page: Callable[[PagePipelineResult], None] | None = None,
        temporary_template: TableTemplate | None = None,
    ) -> DocumentPipelineResult: ...


class ProjectRunService:
    def __init__(self, store: ProjectStore, processor: _Processor) -> None:
        self.store = store
        self.processor = processor

    def start(
        self,
        project_id: int,
        manifest: RunManifest,
        source: str | Path,
        *,
        dpi: int,
        checkpoint: Callable[[], None] | None = None,
    ) -> tuple[int, DocumentPipelineResult]:
        run_id = self.store.create_run(project_id, manifest, _source_sha256(source))
        self.store.set_run_status(run_id, "running")
        self._seed_pending_pages(run_id, source)
        return run_id, self._process(run_id, source, dpi=dpi, checkpoint=checkpoint)

    def resume(
        self,
        run_id: int,
        source: str | Path,
        *,
        dpi: int,
        manifest: RunManifest | None = None,
        checkpoint: Callable[[], None] | None = None,
        reprocess_review_pages: bool = False,
    ) -> DocumentPipelineResult:
        if manifest is not None and self.store.get_run_manifest(run_id) != manifest:
            raise ValueError("run manifest mismatch; refusing to resume the run")
        expected_sha256 = self.store.get_run_source_sha256(run_id)
        actual_sha256 = _source_sha256(source)
        if expected_sha256 is not None and actual_sha256 != expected_sha256:
            raise ValueError("source file checksum mismatch; refusing to resume the run")
        if reprocess_review_pages:
            self.store.requeue_review_pages(run_id)
        status = self.store.get_run_status(run_id)
        if status == "completed":
            pages = self.store.resume_pages(run_id)
            if not pages:
                return _empty_result(source)
        else:
            self._seed_pending_pages(run_id, source)
            pages = self.store.resume_pages(run_id)
        if status == "needs_review" and not pages:
            return _empty_result(source)
        self.store.set_run_status(run_id, "running")
        page_indexes = pages or None
        return self._process(
            run_id,
            source,
            dpi=dpi,
            page_indexes=page_indexes,
            checkpoint=checkpoint,
        )

    def _seed_pending_pages(self, run_id: int, source: str | Path) -> None:
        path = Path(source)
        if not path.is_file():
            return
        try:
            page_indexes = (signals.page_index for signals in PdfReader(path).iter_signals())
            self.store.seed_page_states(run_id, page_indexes)
        except Exception:
            # The processor owns detailed source errors; seeding is only a recovery aid.
            return

    def _process(
        self,
        run_id: int,
        source: str | Path,
        *,
        dpi: int,
        page_indexes: Iterable[int] | None = None,
        checkpoint: Callable[[], None] | None = None,
    ) -> DocumentPipelineResult:
        persisted_pages: set[int] = set()

        def on_page(page: object) -> None:
            if not isinstance(page, PagePipelineResult):
                raise TypeError("processor on_page callback must receive PagePipelineResult")
            self._persist_page(run_id, page)
            persisted_pages.add(page.page_index)
            if checkpoint is not None:
                checkpoint()

        try:
            process_kwargs = {
                "dpi": dpi,
                "page_indexes": page_indexes,
                "on_page": on_page,
            }
            temporary_record = self.store.load_temporary_template(run_id)
            if temporary_record is not None:
                process_kwargs["temporary_template"] = temporary_record.template
            result = self.processor.process(source, **process_kwargs)
        except Exception:
            self.store.set_run_status(run_id, "failed")
            raise
        for page in result.pages:
            if page.page_index not in persisted_pages:
                self._persist_page(run_id, page)
        self._finalize_run(run_id)
        return result

    def _persist(self, run_id: int, result: DocumentPipelineResult) -> None:
        for page in result.pages:
            self._persist_page(run_id, page)
        self._finalize_run(run_id)

    def _persist_page(self, run_id: int, page: PagePipelineResult) -> None:
        if page.classification.kind is PageKind.PAGE_ERROR:
            page_status = "failed"
        elif page.parser_outcome.status in {
            ParserOutcomeStatus.FAILED,
            ParserOutcomeStatus.PAGE_REVIEW,
        }:
            page_status = "needs_review"
        elif page.validation_report is not None and (
            page.validation_report.status is not None
            and page.validation_report.status.value in {"review", "page_review"}
        ):
            page_status = "needs_review"
        else:
            page_status = "completed"
        page_error = page.parser_outcome.reason or page.classification.error
        self.store.save_page_result(
            run_id,
            page.page_index,
            page.parser_outcome.candidates,
            page.ocr_result,
            page.validation_report,
            page_status,
            error=page_error,
        )

    def _finalize_run(self, run_id: int) -> None:
        validator = getattr(self.processor, "validator", None)
        if validator is not None and hasattr(validator, "validate_document"):
            reports = validator.validate_document(
                self.store.load_candidates(run_id),
                blocks_by_page=self.store.load_ocr_blocks(run_id),
            )
            for page_index, report in reports.items():
                self.store.save_validation_report(run_id, page_index, report)
            self.store.refresh_run_status(run_id)
            return
        statuses = self.store.page_statuses(run_id)
        if any(status == "failed" for status in statuses):
            run_status = "failed"
        elif any(status == "needs_review" for status in statuses):
            run_status = "needs_review"
        elif statuses and all(status == "completed" for status in statuses):
            run_status = "completed"
        else:
            run_status = "running"
        self.store.set_run_status(run_id, run_status)


def _source_sha256(source: str | Path) -> str | None:
    path = Path(source)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _empty_result(source: str | Path) -> DocumentPipelineResult:
    return DocumentPipelineResult(file=Path(source).name, pages=())
