"""PDF task queue integration with cooperative controls and bounded resources."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable

from bankocr.domain.run_manifest import RunManifest
from bankocr.export.comparison_pdf import ComparisonPdfExporter
from bankocr.export.excel import ExcelExporter
from bankocr.export.manifest import ExportManifest, count_unresolved
from bankocr.export.pdf_layout import PdfLayoutExcelExporter
from bankocr.export.review import ReviewExcelExporter
from bankocr.export.searchable_pdf import SearchablePdfExporter
from bankocr.pdf.preflight import PdfPreflight, run_preflight
from bankocr.pipeline.run_service import ProjectRunService

from .manager import Task, TaskControl, TaskExecutor, TaskManager, TaskSnapshot


@dataclass(frozen=True, slots=True)
class ResourcePolicy:
    name: str = "standard"
    max_parallel: int = 1
    dpi: int = 200

    def __post_init__(self) -> None:
        if self.name not in {"standard", "low"}:
            raise ValueError("resource policy must be standard or low")
        if self.max_parallel != 1:
            raise ValueError("the CPU-first release policy permits one main PDF at a time")
        if self.dpi <= 0:
            raise ValueError("dpi must be positive")

    @classmethod
    def low_resource(cls) -> ResourcePolicy:
        return cls(name="low", max_parallel=1, dpi=150)


@dataclass(frozen=True, slots=True)
class PdfTask:
    source: Path
    project_id: int
    manifest: RunManifest
    output_dir: Path | None = None
    dpi: int | None = None
    font_file: Path | None = None


class PdfTaskExecutor(TaskExecutor):
    def __init__(
        self,
        service: ProjectRunService,
        *,
        policy: ResourcePolicy | None = None,
        on_progress: Callable[[object], None] | None = None,
    ) -> None:
        self.service = service
        self.policy = policy or ResourcePolicy()
        self.on_progress = on_progress
        self._run_ids: dict[str, int] = {}

    def execute(self, task: Task, control: TaskControl) -> object:
        if not isinstance(task.payload, PdfTask):
            raise TypeError("PDF task payload must be PdfTask")
        payload = task.payload
        control.checkpoint()
        preflight = run_preflight(
            payload.source,
            output_dir=payload.output_dir,
            output_paths=_output_paths(payload),
            minimum_free_bytes=max(payload.source.stat().st_size * 3, 64 * 1024 * 1024),
        )
        if task.task_id in self._run_ids:
            run_id = self._run_ids[task.task_id]
            result = self.service.resume(
                run_id,
                payload.source,
                dpi=payload.dpi or self.policy.dpi,
                manifest=payload.manifest,
                checkpoint=control.checkpoint,
            )
        else:
            run_id, result = self.service.start(
                payload.project_id,
                payload.manifest,
                payload.source,
                dpi=payload.dpi or self.policy.dpi,
                checkpoint=control.checkpoint,
            )
            self._run_ids[task.task_id] = run_id
        artifacts = (
            self._export_artifacts(payload, run_id, preflight)
            if payload.output_dir is not None
            else {}
        )
        if self.on_progress is not None:
            self.on_progress(result)
        control.checkpoint()
        return {"run_id": run_id, "result": result, "artifacts": artifacts}

    def _export_artifacts(
        self,
        payload: PdfTask,
        run_id: int,
        preflight: PdfPreflight,
    ) -> dict[str, str]:
        store = self.service.store
        output_dir = payload.output_dir
        if output_dir is None:
            return {}
        output_dir.mkdir(parents=True, exist_ok=True)
        candidates = store.load_candidates(run_id)
        reports = store.load_validation_reports(run_id)
        blocks = store.load_ocr_blocks(run_id)
        errors = store.page_errors(run_id)
        stem = payload.source.stem
        excel = ExcelExporter().export(
            candidates,
            output_dir / f"{stem}.xlsx",
            source_file=payload.source.name,
            validation_reports=reports,
            metadata={
                **payload.manifest.to_dict(),
                "source_sha256": preflight.source_sha256,
            },
            blocks_by_page=blocks,
        )
        review = ReviewExcelExporter().export(
            candidates,
            reports,
            output_dir / f"{stem}.review.xlsx",
            source_file=payload.source.name,
            page_errors=errors,
        )
        pdf_layout_excel = PdfLayoutExcelExporter().export(
            payload.source,
            output_dir / f"{stem}.pdf-layout.xlsx",
            candidates,
        )
        searchable = SearchablePdfExporter(font_file=payload.font_file).export(
            payload.source,
            output_dir / f"{stem}.searchable.pdf",
            blocks,
        )
        comparison = ComparisonPdfExporter(font_file=payload.font_file).export(
            payload.source,
            output_dir / f"{stem}.comparison.pdf",
            candidates,
            blocks,
            validation_reports=reports,
        )
        export_manifest = ExportManifest.create(
            run_id=run_id,
            source_sha256=preflight.source_sha256,
            unresolved_count=count_unresolved(candidates, reports, errors),
            outputs={
                "excel": excel,
                "review_excel": review,
                "pdf_layout_excel": pdf_layout_excel,
                "searchable_pdf": searchable,
                "comparison_pdf": comparison,
            },
        )
        export_manifest_path = export_manifest.write(
            output_dir / f"{stem}.export-manifest.json"
        )
        counts: dict[int, int] = {}
        for candidate in candidates:
            counts[candidate.page_index] = counts.get(candidate.page_index, 0) + 1
        summary_path = output_dir / f"{stem}.summary.json"
        summary_path.write_text(
            json.dumps(
                {
                    "file": payload.source.name,
                    "run_id": run_id,
                    "run_status": store.get_run_status(run_id),
                    "outputs": {
                        "excel": excel.name,
                        "review_excel": review.name,
                        "pdf_layout_excel": pdf_layout_excel.name,
                        "searchable_pdf": searchable.name,
                        "comparison_pdf": comparison.name,
                        "export_manifest": export_manifest_path.name,
                    },
                    "preflight": {
                        "page_count": preflight.page_count,
                        "blank_pages": list(preflight.blank_pages),
                        "repeated_pages": [list(group) for group in preflight.repeated_pages],
                        "rotated_pages": list(preflight.rotated_pages),
                        "warnings": list(preflight.warnings),
                    },
                    "pages": [
                        {
                            "page_index": page_index,
                            "state": state,
                            "candidate_count": counts.get(page_index, 0),
                            "validation_status": reports[page_index].status.value
                            if page_index in reports and reports[page_index].status is not None
                            else "unknown",
                            "risk_score": reports[page_index].risk_score
                            if page_index in reports
                            else None,
                        }
                        for page_index, state in store.page_states(run_id)
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "excel": str(excel),
            "review_excel": str(review),
            "pdf_layout_excel": str(pdf_layout_excel),
            "searchable_pdf": str(searchable),
            "comparison_pdf": str(comparison),
            "export_manifest": str(export_manifest_path),
            "summary": str(summary_path),
        }

    def export_existing(self, payload: PdfTask, run_id: int) -> dict[str, str]:
        """Re-export a persisted run after human review without rerunning OCR."""

        preflight = run_preflight(
            payload.source,
            output_dir=payload.output_dir,
            output_paths=_output_paths(payload),
            minimum_free_bytes=max(payload.source.stat().st_size * 3, 64 * 1024 * 1024),
        )
        return self._export_artifacts(payload, run_id, preflight)


def _output_paths(payload: PdfTask) -> tuple[Path, ...]:
    if payload.output_dir is None:
        return ()
    stem = payload.source.stem
    return (
        payload.output_dir / f"{stem}.xlsx",
        payload.output_dir / f"{stem}.review.xlsx",
        payload.output_dir / f"{stem}.pdf-layout.xlsx",
        payload.output_dir / f"{stem}.searchable.pdf",
        payload.output_dir / f"{stem}.comparison.pdf",
        payload.output_dir / f"{stem}.export-manifest.json",
        payload.output_dir / f"{stem}.summary.json",
    )


class PdfTaskQueue:
    """User-facing queue facade; TaskManager supplies lifecycle guarantees."""

    def __init__(self, executor: PdfTaskExecutor) -> None:
        self.executor = executor
        self.manager = TaskManager(executor)

    def submit(self, payload: PdfTask, *, task_id: str | None = None) -> str:
        return self.manager.submit(payload, task_id=task_id)

    def run_next(self) -> TaskSnapshot | None:
        return self.manager.run_next()

    def run_all(self) -> tuple[TaskSnapshot, ...]:
        return self.manager.run_all()

    def pause(self, task_id: str) -> TaskSnapshot:
        return self.manager.pause(task_id)

    def resume(self, task_id: str) -> TaskSnapshot:
        return self.manager.resume(task_id)

    def cancel(self, task_id: str) -> TaskSnapshot:
        return self.manager.cancel(task_id)

    def restart(self, task_id: str) -> TaskSnapshot:
        return self.manager.restart(task_id)

    def update_result(self, task_id: str, result: object) -> TaskSnapshot:
        return self.manager.update_result(task_id, result)
