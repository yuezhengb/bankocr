"""Immutable per-export hashes separate from the pinned Run Manifest."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping
from uuid import uuid4


def count_unresolved(
    candidates: Iterable[object],
    reports: Mapping[int, object],
    page_errors: Mapping[int, str],
) -> int:
    """Count rows on review pages plus page-level errors without double counting.

    A machine-generated candidate can remain ``unreviewed`` even when its page
    passed all deterministic checks, so candidate status alone is not a useful
    export gate.  The report/page state is the authoritative signal here.
    """

    review_pages = {
        page_index
        for page_index, report in reports.items()
        if getattr(getattr(report, "status", None), "value", None)
        in {"review", "page_review"}
    }
    unresolved_rows = sum(
        1 for candidate in candidates if getattr(candidate, "page_index", None) in review_pages
    )
    unresolved_pages = len(set(page_errors) - review_pages)
    return unresolved_rows + unresolved_pages


@dataclass(frozen=True, slots=True)
class ExportArtifact:
    name: str
    filename: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ExportManifest:
    format_version: int
    export_id: str
    run_id: int | None
    source_sha256: str | None
    exported_at: str
    unresolved_count: int
    outputs: Mapping[str, ExportArtifact]

    @classmethod
    def create(
        cls,
        *,
        run_id: int | None,
        source_sha256: str | None,
        unresolved_count: int,
        outputs: Mapping[str, str | Path],
    ) -> "ExportManifest":
        if unresolved_count < 0:
            raise ValueError("unresolved_count must be non-negative")
        if source_sha256 is not None and len(source_sha256) != 64:
            raise ValueError("source_sha256 must be a SHA-256 hex digest")
        artifacts: dict[str, ExportArtifact] = {}
        for name, raw_path in outputs.items():
            path = Path(raw_path)
            if not path.is_file():
                raise FileNotFoundError(path)
            artifacts[str(name)] = ExportArtifact(
                name=str(name),
                filename=path.name,
                size=path.stat().st_size,
                sha256=_sha256(path),
            )
        if not artifacts:
            raise ValueError("at least one output artifact is required")
        return cls(
            format_version=1,
            export_id=uuid4().hex,
            run_id=run_id,
            source_sha256=source_sha256,
            exported_at=datetime.now(timezone.utc).isoformat(),
            unresolved_count=unresolved_count,
            outputs=artifacts,
        )

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["outputs"] = {
            name: asdict(artifact)
            for name, artifact in self.outputs.items()
        }
        return payload

    def write(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return destination


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
