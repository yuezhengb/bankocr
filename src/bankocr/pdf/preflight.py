"""Document-level safety checks kept separate from page processing."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil

from .classifier import PageClassification, PageClassifier, PageKind, PageSignals
from .reader import PdfReader


class PdfPreflightError(ValueError):
    """Raised when the input/output contract cannot be satisfied safely."""


@dataclass(frozen=True, slots=True)
class PdfPreflight:
    source: Path
    source_sha256: str
    file_size: int
    page_count: int
    signals: tuple[PageSignals, ...]
    classifications: tuple[PageClassification, ...]
    blank_pages: tuple[int, ...]
    repeated_pages: tuple[tuple[int, ...], ...]
    rotated_pages: tuple[int, ...]
    warnings: tuple[str, ...]

    @property
    def page_errors(self) -> dict[int, str]:
        return {
            item.page_index: item.error or "page error"
            for item in self.classifications
            if item.kind is PageKind.PAGE_ERROR
        }

    @property
    def has_errors(self) -> bool:
        return bool(self.page_errors)


def run_preflight(
    source: str | Path,
    *,
    output_dir: str | Path | None = None,
    output_paths: tuple[str | Path, ...] = (),
    minimum_free_bytes: int = 0,
    maximum_file_size: int | None = None,
) -> PdfPreflight:
    source_path = Path(source).expanduser().resolve()
    if not source_path.is_file():
        raise PdfPreflightError(f"source PDF does not exist: {source_path}")
    file_size = source_path.stat().st_size
    if file_size <= 0:
        raise PdfPreflightError("source PDF is empty")
    if maximum_file_size is not None and maximum_file_size <= 0:
        raise ValueError("maximum_file_size must be positive")
    if maximum_file_size is not None and file_size > maximum_file_size:
        raise PdfPreflightError("source PDF exceeds the configured size limit")
    if output_dir is not None:
        output_path = Path(output_dir).expanduser().resolve()
        output_path.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(output_path).free < minimum_free_bytes:
            raise PdfPreflightError("not enough free disk space for the requested output")
    for output in output_paths:
        if source_path == Path(output).expanduser().resolve():
            raise PdfPreflightError("an output path would overwrite the source PDF")

    try:
        signals = tuple(PdfReader(source_path).iter_signals())
    except Exception as exc:
        raise PdfPreflightError(f"PDF cannot be opened: {type(exc).__name__}: {exc}") from exc
    if not signals:
        raise PdfPreflightError("PDF contains no pages")
    classifications = tuple(PageClassifier().classify(signal) for signal in signals)
    groups: dict[str, list[int]] = {}
    for signal in signals:
        if signal.content_fingerprint:
            groups.setdefault(signal.content_fingerprint, []).append(signal.page_index)
    repeated = tuple(tuple(indexes) for indexes in groups.values() if len(indexes) > 1)
    warnings: list[str] = []
    if repeated:
        warnings.append("repeated page content detected")
    if any(item.kind is PageKind.BLANK for item in classifications):
        warnings.append("blank pages detected")
    if any(item.kind is PageKind.PAGE_ERROR for item in classifications):
        warnings.append("one or more pages could not be read")
    if any(item.rotation % 360 for item in signals):
        warnings.append("rotated pages detected; coordinate transform will be retained")
    return PdfPreflight(
        source=source_path,
        source_sha256=_sha256(source_path),
        file_size=file_size,
        page_count=len(signals),
        signals=signals,
        classifications=classifications,
        blank_pages=tuple(item.page_index for item in classifications if item.kind is PageKind.BLANK),
        repeated_pages=repeated,
        rotated_pages=tuple(item.page_index for item in signals if item.rotation % 360),
        warnings=tuple(warnings),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
