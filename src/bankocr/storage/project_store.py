"""Small transactional SQLite store for resumable local processing."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import asdict, dataclass
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from typing import Iterable, Mapping

from bankocr.domain.coordinates import Point
from bankocr.domain.run_manifest import RunManifest
from bankocr.domain.review import ReviewOperation
from bankocr.domain.text_block import SourceSpan, SourceType, TextBlock
from bankocr.ocr.result import OCRPageResult
from bankocr.parser.models import CandidateStatus, FieldValue, TransactionCandidate
from bankocr.parser.template_pack import template_from_dict, template_to_dict
from bankocr.parser.temporary_template import TemporaryTemplateRecord
from bankocr.validation.engine import (
    IssueSeverity,
    ValidationIssue,
    ValidationReport,
    ValidationRuleState,
)
from bankocr.validation.risk import ValidationStatus


class PageState(str):
    """Stable names for persisted page lifecycle states."""

    PENDING = "pending"
    PROCESSING = "running"
    DONE = "completed"
    PAGE_ERROR = "failed"
    REVIEW_REQUIRED = "needs_review"


_PAGE_STATUS_ALIASES = {
    "processing": PageState.PROCESSING,
    "done": PageState.DONE,
    "page_error": PageState.PAGE_ERROR,
    "review_required": PageState.REVIEW_REQUIRED,
}
_PAGE_STATUSES = frozenset(
    {
        PageState.PENDING,
        PageState.PROCESSING,
        PageState.DONE,
        PageState.PAGE_ERROR,
        PageState.REVIEW_REQUIRED,
        *_PAGE_STATUS_ALIASES,
    }
)


@dataclass(frozen=True, slots=True)
class ReviewEvent:
    event_id: int
    run_id: int
    page_index: int
    row_index: int
    action: str
    before_json: str
    after_json: str
    reviewer: str
    created_at: str


class ProjectStore:
    SCHEMA_VERSION = 6

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # The desktop queue owns one worker thread at a time.  The connection
        # is created before that worker starts and is never used concurrently;
        # allowing the hand-off keeps the UI responsive without weakening the
        # single-writer policy.
        self.connection = sqlite3.connect(self.path, timeout=30.0, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = NORMAL")
        self._initialize_schema()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> ProjectStore:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def create_project(self, name: str, source_path: str | Path) -> int:
        if not name:
            raise ValueError("project name must not be empty")
        timestamp = _now()
        cursor = self.connection.execute(
            "INSERT INTO projects(name, source_path, created_at) VALUES (?, ?, ?)",
            (name, str(source_path), timestamp),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def create_run(
        self,
        project_id: int,
        manifest: RunManifest,
        source_sha256: str | None = None,
    ) -> int:
        cursor = self.connection.execute(
            "INSERT INTO runs(project_id, status, manifest_json, source_sha256, created_at, updated_at) "
            "VALUES (?, 'created', ?, ?, ?, ?)",
            (
                project_id,
                json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True),
                source_sha256,
                _now(),
                _now(),
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def set_run_status(self, run_id: int, status: str) -> None:
        if status not in {"created", "running", "completed", "failed", "needs_review"}:
            raise ValueError(f"unknown run status: {status}")
        self.connection.execute(
            "UPDATE runs SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), run_id),
        )
        self.connection.commit()

    def get_run_status(self, run_id: int) -> str:
        row = self.connection.execute(
            "SELECT status FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown run id: {run_id}")
        return str(row["status"])

    def get_run_source_path(self, run_id: int) -> Path:
        row = self.connection.execute(
            "SELECT projects.source_path FROM runs "
            "JOIN projects ON projects.id = runs.project_id WHERE runs.id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown run id: {run_id}")
        return Path(str(row["source_path"]))

    def get_run_source_sha256(self, run_id: int) -> str | None:
        row = self.connection.execute(
            "SELECT source_sha256 FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown run id: {run_id}")
        return row["source_sha256"]

    def get_run_manifest(self, run_id: int) -> RunManifest:
        row = self.connection.execute(
            "SELECT manifest_json FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown run id: {run_id}")
        payload = json.loads(row["manifest_json"])
        if not isinstance(payload, dict):
            raise ValueError(f"invalid manifest for run id: {run_id}")
        return RunManifest(**payload)

    def save_temporary_template(self, record: TemporaryTemplateRecord) -> None:
        """Store a confirmed template without changing the formal template pack."""

        run_exists = self.connection.execute(
            "SELECT 1 FROM runs WHERE id = ?",
            (record.run_id,),
        ).fetchone()
        if run_exists is None:
            raise KeyError(f"unknown run id: {record.run_id}")
        payload = json.dumps(template_to_dict(record.template), ensure_ascii=False, sort_keys=True)
        now = _now()
        existing = self.connection.execute(
            "SELECT created_at FROM temporary_templates WHERE run_id = ?",
            (record.run_id,),
        ).fetchone()
        created_at = now if existing is None else str(existing["created_at"])
        with self.connection:
            self.connection.execute(
                "INSERT INTO temporary_templates(run_id, template_json, source_page_index, confirmed_by, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET template_json=excluded.template_json, "
                "source_page_index=excluded.source_page_index, confirmed_by=excluded.confirmed_by, "
                "updated_at=excluded.updated_at",
                (
                    record.run_id,
                    payload,
                    record.source_page_index,
                    record.confirmed_by.strip(),
                    created_at,
                    now,
                ),
            )

    def load_temporary_template(self, run_id: int) -> TemporaryTemplateRecord | None:
        row = self.connection.execute(
            "SELECT run_id, template_json, source_page_index, confirmed_by, created_at, updated_at "
            "FROM temporary_templates WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["template_json"])
        if not isinstance(payload, dict):
            raise ValueError(f"invalid temporary template for run id: {run_id}")
        return TemporaryTemplateRecord(
            run_id=int(row["run_id"]),
            source_page_index=int(row["source_page_index"]),
            template=template_from_dict(payload, f"temporary template run {run_id}"),
            confirmed_by=str(row["confirmed_by"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def clear_temporary_template(self, run_id: int) -> None:
        with self.connection:
            self.connection.execute(
                "DELETE FROM temporary_templates WHERE run_id = ?",
                (run_id,),
            )

    def schema_version(self) -> int:
        row = self.connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is None:
            raise RuntimeError("project schema version is missing")
        return int(row["value"])

    def save_page_state(self, run_id: int, page_index: int, status: str, error: str | None = None) -> None:
        if status not in _PAGE_STATUSES:
            raise ValueError(f"unknown page status: {status}")
        status = _PAGE_STATUS_ALIASES.get(status, status)
        if page_index < 0:
            raise ValueError("page_index must be non-negative")
        with self.connection:
            self._save_page_state_locked(run_id, page_index, status, error)

    def save_page_result(
        self,
        run_id: int,
        page_index: int,
        candidates: Iterable[TransactionCandidate],
        ocr_result: OCRPageResult | None,
        validation_report: ValidationReport | None,
        status: str,
        error: str | None = None,
    ) -> None:
        """Persist all page artifacts and its state in one SQLite transaction."""

        if status not in _PAGE_STATUSES:
            raise ValueError(f"unknown page status: {status}")
        status = _PAGE_STATUS_ALIASES.get(status, status)
        if page_index < 0:
            raise ValueError("page_index must be non-negative")
        rows = self._candidate_rows(run_id, candidates)
        with self.connection:
            # A retry is a replacement of the page snapshot, not an upsert of
            # individual rows.  Clearing all page artifacts first prevents
            # candidates, OCR blocks, or validation reports from a previous
            # attempt from leaking into exports after a parser returns fewer
            # rows or a retry fails before producing new artifacts.
            self._clear_page_artifacts_locked(run_id, page_index)
            self._upsert_candidate_rows(rows)
            if ocr_result is not None:
                self._save_ocr_result_locked(run_id, ocr_result)
            if validation_report is not None:
                self._save_validation_report_locked(run_id, page_index, validation_report)
            self._save_page_state_locked(run_id, page_index, status, error)

    def _clear_page_artifacts_locked(self, run_id: int, page_index: int) -> None:
        self.connection.execute(
            "DELETE FROM candidates WHERE run_id = ? AND page_index = ?",
            (run_id, page_index),
        )
        self.connection.execute(
            "DELETE FROM ocr_blocks WHERE run_id = ? AND page_index = ?",
            (run_id, page_index),
        )
        self.connection.execute(
            "DELETE FROM validation_reports WHERE run_id = ? AND page_index = ?",
            (run_id, page_index),
        )

    def _save_page_state_locked(
        self,
        run_id: int,
        page_index: int,
        status: str,
        error: str | None,
    ) -> None:
        self.connection.execute(
            "INSERT INTO pages(run_id, page_index, status, error) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(run_id, page_index) DO UPDATE SET status=excluded.status, error=excluded.error",
            (run_id, page_index, status, error),
        )

    def seed_page_states(self, run_id: int, page_indexes: Iterable[int]) -> None:
        indexes = tuple(page_indexes)
        if any(page_index < 0 for page_index in indexes):
            raise ValueError("page_index must be non-negative")
        with self.connection:
            self.connection.executemany(
                "INSERT OR IGNORE INTO pages(run_id, page_index, status) VALUES (?, ?, 'pending')",
                ((run_id, page_index) for page_index in indexes),
            )

    def resume_pages(self, run_id: int) -> tuple[int, ...]:
        rows = self.connection.execute(
            "SELECT page_index FROM pages WHERE run_id = ? "
            "AND status IN ('pending', 'running', 'failed') ORDER BY page_index",
            (run_id,),
        ).fetchall()
        return tuple(int(row["page_index"]) for row in rows)

    def requeue_review_pages(self, run_id: int) -> None:
        """Move PAGE_REVIEW/validation-review pages back to pending for re-run."""

        with self.connection:
            self.connection.execute(
                "UPDATE pages SET status = 'pending', error = NULL "
                "WHERE run_id = ? AND status = 'needs_review'",
                (run_id,),
            )

    def page_statuses(self, run_id: int) -> tuple[str, ...]:
        rows = self.connection.execute(
            "SELECT status FROM pages WHERE run_id = ? ORDER BY page_index",
            (run_id,),
        ).fetchall()
        return tuple(str(row["status"]) for row in rows)

    def page_states(self, run_id: int) -> tuple[tuple[int, str], ...]:
        rows = self.connection.execute(
            "SELECT page_index, status FROM pages WHERE run_id = ? ORDER BY page_index",
            (run_id,),
        ).fetchall()
        return tuple((int(row["page_index"]), str(row["status"])) for row in rows)

    def page_errors(self, run_id: int) -> dict[int, str]:
        rows = self.connection.execute(
            "SELECT page_index, error FROM pages WHERE run_id = ? AND error IS NOT NULL",
            (run_id,),
        ).fetchall()
        return {int(row["page_index"]): str(row["error"]) for row in rows}

    def save_candidates(
        self,
        run_id: int,
        candidates: Iterable[TransactionCandidate],
    ) -> None:
        rows = self._candidate_rows(run_id, candidates)
        with self.connection:
            self._upsert_candidate_rows(rows)

    def save_review(
        self,
        run_id: int,
        candidates: Iterable[TransactionCandidate],
        *,
        validation_reports: Mapping[int, ValidationReport] | None = None,
        reviewer: str = "local-user",
    ) -> None:
        """Persist reviewed candidates and conservatively refresh run status."""

        rows = self._candidate_rows(run_id, candidates)
        with self.connection:
            self._validate_review_rows_locked(rows)
            self._record_review_events_locked(run_id, rows, reviewer)
            self._upsert_candidate_rows(rows)
            for page_index, report in (validation_reports or {}).items():
                self._save_validation_report_locked(run_id, page_index, report)
            self._refresh_review_status_locked(run_id)

    def save_structure_review(
        self,
        run_id: int,
        candidates: Iterable[TransactionCandidate],
        *,
        operations: Iterable[ReviewOperation] = (),
        validation_reports: Mapping[int, ValidationReport] | None = None,
        reviewer: str = "local-user",
    ) -> None:
        """Atomically replace reviewed page snapshots and write structure audit.

        Structure edits can insert or remove source rows, so they cannot use
        the ordinary upsert-only field-review path without leaving stale rows
        behind after a merge or split.
        """

        candidate_values = tuple(candidates)
        operation_values = tuple(operations)
        rows = self._candidate_rows(run_id, candidate_values)
        if not reviewer.strip():
            raise ValueError("reviewer must not be empty")
        with self.connection:
            self._validate_structure_candidates_locked(run_id, candidate_values)
            affected_pages = {candidate.page_index for candidate in candidate_values}
            affected_pages.update(operation.page_index for operation in operation_values)
            before_by_page: dict[int, list[dict[str, object]]] = {}
            after_by_page: dict[int, list[dict[str, object]]] = {}
            for page_index in sorted(affected_pages):
                previous_rows = self.connection.execute(
                    "SELECT page_index, row_index, parser_id, status, duplicate_of_page_index, "
                    "duplicate_of_row_index, review_order, fields_json "
                    "FROM candidates WHERE run_id = ? AND page_index = ? "
                    "ORDER BY COALESCE(review_order, row_index), row_index",
                    (run_id, page_index),
                ).fetchall()
                before_by_page[page_index] = [
                    _candidate_payload_from_row(row) for row in previous_rows
                ]
                after_by_page[page_index] = [
                    _candidate_payload(candidate)
                    for candidate in candidate_values
                    if candidate.page_index == page_index
                ]
                self.connection.execute(
                    "DELETE FROM candidates WHERE run_id = ? AND page_index = ?",
                    (run_id, page_index),
                )
                self._upsert_candidate_rows(
                    row for row in rows if int(row[1]) == page_index
                )

            if operation_values:
                for operation in operation_values:
                    page_index = operation.page_index
                    before = json.dumps(
                        {"candidates": before_by_page.get(page_index, [])},
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    after = json.dumps(
                        {
                            "operation": asdict(operation),
                            "candidates": after_by_page.get(page_index, []),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    self.connection.execute(
                        "INSERT INTO review_events("
                        "run_id, page_index, row_index, action, before_json, after_json, reviewer, created_at"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            run_id,
                            page_index,
                            operation.row_index if operation.row_index is not None else -1,
                            operation.action,
                            before,
                            after,
                            reviewer.strip(),
                            _now(),
                        ),
                    )
            elif affected_pages:
                for page_index in sorted(affected_pages):
                    before = json.dumps(
                        {"candidates": before_by_page.get(page_index, [])},
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    after = json.dumps(
                        {"candidates": after_by_page.get(page_index, [])},
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    if before != after:
                        self.connection.execute(
                            "INSERT INTO review_events("
                            "run_id, page_index, row_index, action, before_json, after_json, reviewer, created_at"
                            ") VALUES (?, ?, -1, 'structure_snapshot', ?, ?, ?, ?)",
                            (run_id, page_index, before, after, reviewer.strip(), _now()),
                        )
            for page_index, report in (validation_reports or {}).items():
                self._save_validation_report_locked(run_id, page_index, report)
            self._refresh_review_status_locked(run_id)

    def save_ocr_result(self, run_id: int, result: OCRPageResult) -> None:
        with self.connection:
            self._save_ocr_result_locked(run_id, result)

    def _save_ocr_result_locked(self, run_id: int, result: OCRPageResult) -> None:
        rows = []
        for block_index, block in enumerate(result.blocks):
            rows.append(
                (
                    run_id,
                    result.page_index,
                    block_index,
                    block.text,
                    block.raw_text,
                    json.dumps(
                        [(point.x, point.y) for point in block.polygon],
                        ensure_ascii=False,
                    ),
                    block.confidence,
                    block.source_type.value,
                    block.engine_id,
                    block.text_block_id,
                )
            )
        self.connection.execute(
            "DELETE FROM ocr_blocks WHERE run_id = ? AND page_index = ?",
            (run_id, result.page_index),
        )
        self.connection.executemany(
            "INSERT INTO ocr_blocks("
            "run_id, page_index, block_index, text, raw_text, polygon_json, confidence, source_type, engine_id, text_block_id"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    def load_ocr_blocks(self, run_id: int) -> dict[int, tuple[TextBlock, ...]]:
        rows = self.connection.execute(
            "SELECT page_index, text, raw_text, polygon_json, confidence, source_type, engine_id, text_block_id "
            "FROM ocr_blocks WHERE run_id = ? ORDER BY page_index, block_index",
            (run_id,),
        ).fetchall()
        blocks: dict[int, list[TextBlock]] = {}
        for row in rows:
            page_index = int(row["page_index"])
            blocks.setdefault(page_index, []).append(
                TextBlock(
                    text=str(row["text"]),
                    raw_text=str(row["raw_text"]),
                    polygon=tuple(
                        Point(float(x), float(y))
                        for x, y in json.loads(row["polygon_json"])
                    ),
                    confidence=None
                    if row["confidence"] is None
                    else float(row["confidence"]),
                    source_type=_source_type(row["source_type"]),
                    page_index=page_index,
                    engine_id=str(row["engine_id"]),
                    text_block_id=str(row["text_block_id"] or ""),
                )
            )
        return {page: tuple(values) for page, values in blocks.items()}

    def load_review_events(self, run_id: int) -> tuple[ReviewEvent, ...]:
        rows = self.connection.execute(
            "SELECT id, run_id, page_index, row_index, action, before_json, after_json, reviewer, created_at "
            "FROM review_events WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        return tuple(
            ReviewEvent(
                event_id=int(row["id"]),
                run_id=int(row["run_id"]),
                page_index=int(row["page_index"]),
                row_index=int(row["row_index"]),
                action=str(row["action"]),
                before_json=str(row["before_json"]),
                after_json=str(row["after_json"]),
                reviewer=str(row["reviewer"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        )

    def load_candidates(self, run_id: int) -> tuple[TransactionCandidate, ...]:
        rows = self.connection.execute(
            "SELECT page_index, row_index, parser_id, status, duplicate_of_page_index, "
            "duplicate_of_row_index, review_order, fields_json "
            "FROM candidates WHERE run_id = ? "
            "ORDER BY page_index, COALESCE(review_order, row_index), row_index",
            (run_id,),
        ).fetchall()
        candidates: list[TransactionCandidate] = []
        for row in rows:
            raw_fields = json.loads(row["fields_json"])
            fields = {
                name: FieldValue(
                    raw_text=value["raw_text"],
                    suggested_text=value["suggested_text"],
                    final_text=value["final_text"],
                    secondary_text=value.get("secondary_text"),
                    confidence=value["confidence"],
                    source_block_indices=tuple(value["source_block_indices"]),
                    source_spans=tuple(
                        SourceSpan(
                            page_index=int(span["page_index"]),
                            polygon=tuple(
                                Point(float(x), float(y))
                                for x, y in span["polygon"]
                            ),
                            text_block_id=str(span["text_block_id"]),
                        )
                        for span in value.get("source_spans", ())
                    ),
                )
                for name, value in raw_fields.items()
            }
            candidates.append(
                TransactionCandidate(
                    page_index=int(row["page_index"]),
                    row_index=int(row["row_index"]),
                    parser_id=row["parser_id"],
                    fields=fields,
                    status=CandidateStatus(row["status"]),
                    duplicate_of=None
                    if row["duplicate_of_page_index"] is None
                    else (
                        int(row["duplicate_of_page_index"]),
                        int(row["duplicate_of_row_index"]),
                    ),
                    review_order=None
                    if row["review_order"] is None
                    else int(row["review_order"]),
                )
            )
        return tuple(candidates)

    def save_validation_report(
        self,
        run_id: int,
        page_index: int,
        report: ValidationReport,
    ) -> None:
        if page_index < 0:
            raise ValueError("page_index must be non-negative")
        with self.connection:
            self._save_validation_report_locked(run_id, page_index, report)

    def refresh_run_status(self, run_id: int) -> None:
        """Recompute review/page/run statuses after a document-level pass."""

        with self.connection:
            self._refresh_statuses_locked(run_id)

    def _save_validation_report_locked(
        self,
        run_id: int,
        page_index: int,
        report: ValidationReport,
    ) -> None:
        if page_index < 0:
            raise ValueError("page_index must be non-negative")
        issues = [
            {
                "code": issue.code,
                "message": issue.message,
                "severity": issue.severity.value,
                "row_index": issue.row_index,
                "field_name": issue.field_name,
                "source_page_index": issue.source_page_index,
                "source_block_indices": list(issue.source_block_indices),
                "source_bbox": None if issue.source_bbox is None else list(issue.source_bbox),
                "rule_state": issue.rule_state.value,
            }
            for issue in report.issues
        ]
        balances = [None if balance is None else str(balance) for balance in report.final_balances]
        self.connection.execute(
            "INSERT INTO validation_reports(run_id, page_index, checked_rows, issues_json, balances_json, status, risk_score, reasons_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id, page_index) DO UPDATE SET "
            "checked_rows=excluded.checked_rows, issues_json=excluded.issues_json, "
            "balances_json=excluded.balances_json, status=excluded.status, "
            "risk_score=excluded.risk_score, reasons_json=excluded.reasons_json",
            (
                run_id,
                page_index,
                report.checked_rows,
                json.dumps(issues, ensure_ascii=False, sort_keys=True),
                json.dumps(balances, ensure_ascii=False),
                report.status.value if report.status is not None else None,
                report.risk_score,
                json.dumps(report.reasons, ensure_ascii=False),
            ),
        )

    def load_validation_reports(self, run_id: int) -> dict[int, ValidationReport]:
        rows = self.connection.execute(
            "SELECT page_index, checked_rows, issues_json, balances_json, status, risk_score, reasons_json "
            "FROM validation_reports WHERE run_id = ? ORDER BY page_index",
            (run_id,),
        ).fetchall()
        reports: dict[int, ValidationReport] = {}
        for row in rows:
            issues = tuple(
                ValidationIssue(
                    code=value["code"],
                    message=value["message"],
                    severity=IssueSeverity(value["severity"]),
                    row_index=int(value["row_index"]),
                    field_name=value["field_name"],
                    source_page_index=value.get("source_page_index"),
                    source_block_indices=tuple(value.get("source_block_indices", ())),
                    source_bbox=None
                    if value.get("source_bbox") is None
                    else tuple(float(item) for item in value["source_bbox"]),
                    rule_state=ValidationRuleState(
                        value.get("rule_state", ValidationRuleState.FAIL.value)
                    ),
                )
                for value in json.loads(row["issues_json"])
            )
            balances = tuple(
                None if value is None else Decimal(value)
                for value in json.loads(row["balances_json"])
            )
            reports[int(row["page_index"])] = ValidationReport(
                checked_rows=int(row["checked_rows"]),
                issues=issues,
                final_balances=balances,
                status=None if row["status"] is None else ValidationStatus(row["status"]),
                risk_score=None if row["risk_score"] is None else int(row["risk_score"]),
                reasons=tuple(json.loads(row["reasons_json"] or "[]")),
            )
        return reports

    def _initialize_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                source_path TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                status TEXT NOT NULL,
                manifest_json TEXT NOT NULL,
                source_sha256 TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pages (
                run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                page_index INTEGER NOT NULL,
                status TEXT NOT NULL,
                error TEXT,
                PRIMARY KEY(run_id, page_index)
            );
            CREATE TABLE IF NOT EXISTS candidates (
                run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                page_index INTEGER NOT NULL,
                row_index INTEGER NOT NULL,
                parser_id TEXT NOT NULL,
                status TEXT NOT NULL,
                fields_json TEXT NOT NULL,
                duplicate_of_page_index INTEGER,
                duplicate_of_row_index INTEGER,
                review_order INTEGER,
                PRIMARY KEY(run_id, page_index, row_index)
            );
            CREATE TABLE IF NOT EXISTS validation_reports (
                run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                page_index INTEGER NOT NULL,
                checked_rows INTEGER NOT NULL,
                issues_json TEXT NOT NULL,
                balances_json TEXT NOT NULL,
                status TEXT,
                risk_score INTEGER,
                reasons_json TEXT NOT NULL DEFAULT '[]',
                PRIMARY KEY(run_id, page_index)
            );
            CREATE TABLE IF NOT EXISTS ocr_blocks (
                run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                page_index INTEGER NOT NULL,
                block_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                raw_text TEXT NOT NULL,
                polygon_json TEXT NOT NULL,
                confidence REAL,
                source_type TEXT NOT NULL,
                engine_id TEXT NOT NULL,
                text_block_id TEXT,
                PRIMARY KEY(run_id, page_index, block_index)
            );
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS review_events (
                id INTEGER PRIMARY KEY,
                run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                page_index INTEGER NOT NULL,
                row_index INTEGER NOT NULL,
                action TEXT NOT NULL,
                before_json TEXT NOT NULL,
                after_json TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS temporary_templates (
                run_id INTEGER PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
                template_json TEXT NOT NULL,
                source_page_index INTEGER NOT NULL,
                confirmed_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        columns = {
            str(row[1])
            for row in self.connection.execute("PRAGMA table_info(runs)").fetchall()
        }
        existing_version = self._read_schema_version()
        version = 1 if existing_version is None else existing_version
        if version > self.SCHEMA_VERSION:
            raise RuntimeError(
                f"project schema {version} is newer than supported {self.SCHEMA_VERSION}"
            )
        with self.connection:
            while version < self.SCHEMA_VERSION:
                migration = getattr(self, f"_migrate_v{version}_to_v{version + 1}")
                migration()
                version += 1
                self.connection.execute(
                    "INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (str(version),),
                )
            final_run_columns = {
                str(row[1])
                for row in self.connection.execute("PRAGMA table_info(runs)").fetchall()
            }
            if "source_sha256" not in final_run_columns:
                self.connection.execute("ALTER TABLE runs ADD COLUMN source_sha256 TEXT")
            self.connection.execute(
                "INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(self.SCHEMA_VERSION),),
            )
        self.connection.commit()

    def _read_schema_version(self) -> int | None:
        table = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'"
        ).fetchone()
        if table is None:
            return None
        row = self.connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
        return None if row is None else int(row["value"])

    def _migrate_v1_to_v2(self) -> None:
        columns = {
            str(row[1])
            for row in self.connection.execute("PRAGMA table_info(runs)").fetchall()
        }
        if "source_sha256" not in columns:
            self.connection.execute("ALTER TABLE runs ADD COLUMN source_sha256 TEXT")

    def _migrate_v2_to_v3(self) -> None:
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS review_events (
                id INTEGER PRIMARY KEY,
                run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                page_index INTEGER NOT NULL,
                row_index INTEGER NOT NULL,
                action TEXT NOT NULL,
                before_json TEXT NOT NULL,
                after_json TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )

    def _migrate_v3_to_v4(self) -> None:
        columns = {
            str(row[1])
            for row in self.connection.execute("PRAGMA table_info(validation_reports)").fetchall()
        }
        if "status" not in columns:
            self.connection.execute("ALTER TABLE validation_reports ADD COLUMN status TEXT")
        if "risk_score" not in columns:
            self.connection.execute("ALTER TABLE validation_reports ADD COLUMN risk_score INTEGER")
        if "reasons_json" not in columns:
            self.connection.execute(
                "ALTER TABLE validation_reports ADD COLUMN reasons_json TEXT NOT NULL DEFAULT '[]'"
            )

    def _migrate_v4_to_v5(self) -> None:
        columns = {
            str(row[1])
            for row in self.connection.execute("PRAGMA table_info(ocr_blocks)").fetchall()
        }
        if "text_block_id" not in columns:
            self.connection.execute("ALTER TABLE ocr_blocks ADD COLUMN text_block_id TEXT")
        self.connection.execute(
            "UPDATE ocr_blocks SET text_block_id = 'p' || printf('%04d:legacy:%06d', page_index, block_index) "
            "WHERE text_block_id IS NULL OR text_block_id = ''"
        )

    def _migrate_v5_to_v6(self) -> None:
        candidate_columns = {
            str(row[1])
            for row in self.connection.execute("PRAGMA table_info(candidates)").fetchall()
        }
        if "duplicate_of_page_index" not in candidate_columns:
            self.connection.execute(
                "ALTER TABLE candidates ADD COLUMN duplicate_of_page_index INTEGER"
            )
        if "duplicate_of_row_index" not in candidate_columns:
            self.connection.execute(
                "ALTER TABLE candidates ADD COLUMN duplicate_of_row_index INTEGER"
            )
        if "review_order" not in candidate_columns:
            self.connection.execute("ALTER TABLE candidates ADD COLUMN review_order INTEGER")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS temporary_templates (
                run_id INTEGER PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
                template_json TEXT NOT NULL,
                source_page_index INTEGER NOT NULL,
                confirmed_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )

    @staticmethod
    def _candidate_rows(
        run_id: int,
        candidates: Iterable[TransactionCandidate],
    ) -> list[tuple[object, ...]]:
        rows = []
        for candidate in candidates:
            fields = {
                name: {
                    "raw_text": value.raw_text,
                    "secondary_text": value.secondary_text,
                    "suggested_text": value.suggested_text,
                    "final_text": value.final_text,
                    "confidence": value.confidence,
                    "source_block_indices": list(value.source_block_indices),
                    "source_spans": [
                        {
                            "page_index": span.page_index,
                            "polygon": [(point.x, point.y) for point in span.polygon],
                            "text_block_id": span.text_block_id,
                        }
                        for span in value.source_spans
                    ],
                }
                for name, value in candidate.fields
            }
            rows.append(
                (
                    run_id,
                    candidate.page_index,
                    candidate.row_index,
                    candidate.parser_id,
                    candidate.status.value,
                    json.dumps(fields, ensure_ascii=False, sort_keys=True),
                    None if candidate.duplicate_of is None else candidate.duplicate_of[0],
                    None if candidate.duplicate_of is None else candidate.duplicate_of[1],
                    candidate.review_order,
                )
            )
        return rows

    def _upsert_candidate_rows(self, rows: Iterable[tuple[object, ...]]) -> None:
        self.connection.executemany(
            "INSERT INTO candidates(run_id, page_index, row_index, parser_id, status, fields_json, "
            "duplicate_of_page_index, duplicate_of_row_index, review_order) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id, page_index, row_index) DO UPDATE SET "
            "parser_id=excluded.parser_id, status=excluded.status, fields_json=excluded.fields_json, "
            "duplicate_of_page_index=excluded.duplicate_of_page_index, "
            "duplicate_of_row_index=excluded.duplicate_of_row_index, review_order=excluded.review_order",
            rows,
        )

    def _validate_review_rows_locked(self, rows: Iterable[tuple[object, ...]]) -> None:
        for row in rows:
            _, page_index, row_index, _, _, _, _, _, _ = row
            exists = self.connection.execute(
                "SELECT 1 FROM candidates WHERE run_id = ? AND page_index = ? AND row_index = ?",
                (row[0], page_index, row_index),
            ).fetchone()
            if exists is None:
                raise ValueError(
                    f"candidate ({page_index}, {row_index}) does not belong to run {row[0]}"
                )

    def _record_review_events_locked(
        self,
        run_id: int,
        rows: Iterable[tuple[object, ...]],
        reviewer: str,
    ) -> None:
        if not reviewer.strip():
            raise ValueError("reviewer must not be empty")
        for row in rows:
            (
                _,
                page_index,
                row_index,
                _,
                status,
                fields_json,
                duplicate_of_page_index,
                duplicate_of_row_index,
                review_order,
            ) = row
            previous = self.connection.execute(
                "SELECT status, fields_json, duplicate_of_page_index, duplicate_of_row_index, review_order "
                "FROM candidates "
                "WHERE run_id = ? AND page_index = ? AND row_index = ?",
                (run_id, page_index, row_index),
            ).fetchone()
            if previous is None:
                continue
            before = json.dumps(
                {
                    "status": previous["status"],
                    "duplicate_of": _duplicate_of_from_columns(previous),
                    "review_order": previous["review_order"],
                    "fields": json.loads(previous["fields_json"]),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            after = json.dumps(
                {
                    "status": status,
                    "duplicate_of": None
                    if duplicate_of_page_index is None
                    else [duplicate_of_page_index, duplicate_of_row_index],
                    "review_order": review_order,
                    "fields": json.loads(fields_json),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            if before == after:
                continue
            self.connection.execute(
                "INSERT INTO review_events("
                "run_id, page_index, row_index, action, before_json, after_json, reviewer, created_at"
                ") VALUES (?, ?, ?, 'candidate_updated', ?, ?, ?, ?)",
                (run_id, page_index, row_index, before, after, reviewer.strip(), _now()),
            )

    def _validate_structure_candidates_locked(
        self,
        run_id: int,
        candidates: tuple[TransactionCandidate, ...],
    ) -> None:
        run_exists = self.connection.execute(
            "SELECT 1 FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if run_exists is None:
            raise KeyError(f"unknown run id: {run_id}")
        identities = [(candidate.page_index, candidate.row_index) for candidate in candidates]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate candidate identity in structure snapshot")
        orders: dict[int, set[int]] = {}
        identity_set = set(identities)
        for candidate in candidates:
            if candidate.review_order is not None:
                page_orders = orders.setdefault(candidate.page_index, set())
                if candidate.review_order in page_orders:
                    raise ValueError("duplicate review order in structure snapshot")
                page_orders.add(candidate.review_order)
            if candidate.duplicate_of is not None and candidate.duplicate_of not in identity_set:
                raise ValueError(
                    "duplicate candidate refers to a candidate outside the structure snapshot"
                )

    def _refresh_review_status_locked(self, run_id: int) -> None:
        page_rows = self.connection.execute(
            "SELECT page_index, status FROM pages WHERE run_id = ? ORDER BY page_index",
            (run_id,),
        ).fetchall()
        for page_row in page_rows:
            if page_row["status"] != "needs_review":
                continue
            page_index = int(page_row["page_index"])
            report_row = self.connection.execute(
                "SELECT issues_json, status FROM validation_reports WHERE run_id = ? AND page_index = ?",
                (run_id, page_index),
            ).fetchone()
            has_validation_issues = _has_actionable_validation_issue(report_row)
            risk_requires_review = bool(
                report_row is not None and report_row["status"] in {"review", "page_review"}
            )
            if not has_validation_issues and not risk_requires_review:
                self.connection.execute(
                    "UPDATE pages SET status = 'completed', error = NULL "
                    "WHERE run_id = ? AND page_index = ?",
                    (run_id, page_index),
                )

        statuses = tuple(
            str(row["status"])
            for row in self.connection.execute(
                "SELECT status FROM pages WHERE run_id = ? ORDER BY page_index",
                (run_id,),
            ).fetchall()
        )
        if any(status == "failed" for status in statuses):
            run_status = "failed"
        elif any(status == "needs_review" for status in statuses):
            run_status = "needs_review"
        elif statuses and all(status == "completed" for status in statuses):
            run_status = "completed"
        else:
            run_status = "running"
        self.connection.execute(
            "UPDATE runs SET status = ?, updated_at = ? WHERE id = ?",
            (run_status, _now(), run_id),
        )

    def _refresh_statuses_locked(self, run_id: int) -> None:
        page_rows = self.connection.execute(
            "SELECT page_index, status, error FROM pages WHERE run_id = ? ORDER BY page_index",
            (run_id,),
        ).fetchall()
        for page_row in page_rows:
            current = str(page_row["status"])
            if current in {"failed", "pending", "running"}:
                continue
            page_index = int(page_row["page_index"])
            report_row = self.connection.execute(
                "SELECT issues_json, status FROM validation_reports WHERE run_id = ? AND page_index = ?",
                (run_id, page_index),
            ).fetchone()
            has_issues = _has_actionable_validation_issue(report_row)
            risk_requires_review = bool(
                report_row is not None and report_row["status"] in {"review", "page_review"}
            )
            needs_review = bool(page_row["error"]) or has_issues or risk_requires_review
            self.connection.execute(
                "UPDATE pages SET status = ?, error = CASE WHEN ? THEN error ELSE NULL END "
                "WHERE run_id = ? AND page_index = ?",
                ("needs_review" if needs_review else "completed", needs_review, run_id, page_index),
            )

        statuses = tuple(
            str(row["status"])
            for row in self.connection.execute(
                "SELECT status FROM pages WHERE run_id = ? ORDER BY page_index",
                (run_id,),
            ).fetchall()
        )
        if any(status == "failed" for status in statuses):
            run_status = "failed"
        elif any(status == "needs_review" for status in statuses):
            run_status = "needs_review"
        elif statuses and all(status == "completed" for status in statuses):
            run_status = "completed"
        else:
            run_status = "running"
        self.connection.execute(
            "UPDATE runs SET status = ?, updated_at = ? WHERE id = ?",
            (run_status, _now(), run_id),
        )

def _candidate_payload(candidate: TransactionCandidate) -> dict[str, object]:
    return {
        "page_index": candidate.page_index,
        "row_index": candidate.row_index,
        "parser_id": candidate.parser_id,
        "status": candidate.status.value,
        "duplicate_of": None
        if candidate.duplicate_of is None
        else list(candidate.duplicate_of),
        "review_order": candidate.review_order,
        "fields": _fields_payload(candidate),
    }


def _candidate_payload_from_row(row: sqlite3.Row) -> dict[str, object]:
    return {
        "page_index": int(row["page_index"]),
        "row_index": int(row["row_index"]),
        "parser_id": str(row["parser_id"]),
        "status": str(row["status"]),
        "duplicate_of": _duplicate_of_from_columns(row),
        "review_order": row["review_order"],
        "fields": json.loads(row["fields_json"]),
    }


def _duplicate_of_from_columns(row: sqlite3.Row) -> list[int] | None:
    if row["duplicate_of_page_index"] is None:
        return None
    return [int(row["duplicate_of_page_index"]), int(row["duplicate_of_row_index"])]


def _fields_payload(candidate: TransactionCandidate) -> dict[str, object]:
    return {
        name: {
            "raw_text": value.raw_text,
            "secondary_text": value.secondary_text,
            "suggested_text": value.suggested_text,
            "final_text": value.final_text,
            "confidence": value.confidence,
            "source_block_indices": list(value.source_block_indices),
            "source_spans": [
                {
                    "page_index": span.page_index,
                    "polygon": [(point.x, point.y) for point in span.polygon],
                    "text_block_id": span.text_block_id,
                }
                for span in value.source_spans
            ],
        }
        for name, value in candidate.fields
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source_type(value: object) -> SourceType:
    """Read both the v1.0 native_text label and the v1.1 native_pdf label."""

    if str(value) == SourceType.NATIVE_TEXT.value:
        return SourceType.NATIVE_PDF
    return SourceType(str(value))


def _has_actionable_validation_issue(row: object) -> bool:
    if row is None:
        return False
    issues = json.loads(row["issues_json"])
    return any(
        issue.get("rule_state", ValidationRuleState.FAIL.value)
        not in {
            ValidationRuleState.PASS.value,
            ValidationRuleState.NOT_APPLICABLE.value,
        }
        for issue in issues
    )
