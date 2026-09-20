"""Memory-bounded OCR baseline runner for page-level benchmark reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import time
from typing import Callable

from bankocr.image.renderer import PdfRenderer
from bankocr.ocr.backend import OCRBackend, OCROptions
from bankocr.ocr.rapidocr_backend import RapidOCRBackend
from bankocr.pdf.classifier import PageClassifier
from bankocr.pdf.reader import PdfReader
from .resources import peak_rss_mb


@dataclass(frozen=True, slots=True)
class PageBaseline:
    page_index: int
    kind: str
    blocks: int = 0
    characters: int = 0
    low_confidence_blocks_lt_080: int = 0
    elapsed_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class DocumentBaseline:
    file: str
    page_count: int
    scan_page_count: int
    total_blocks: int
    pages: tuple[PageBaseline, ...]
    engine_id: str
    dpi: int
    elapsed_seconds: float = 0.0
    peak_rss_mb: float = 0.0

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["pages"] = [asdict(page) for page in self.pages]
        return value


class OCRBaselineRunner:
    def __init__(
        self,
        *,
        backend: OCRBackend | None = None,
        renderer_factory: Callable[[Path], PdfRenderer] = PdfRenderer,
        classifier: PageClassifier | None = None,
    ) -> None:
        self.backend = backend or RapidOCRBackend()
        self.renderer_factory = renderer_factory
        self.classifier = classifier or PageClassifier()

    def run(self, path: str | Path, *, dpi: int = 300) -> DocumentBaseline:
        pdf_path = Path(path)
        if dpi <= 0:
            raise ValueError("dpi must be positive")
        renderer = self.renderer_factory(pdf_path)
        started = time.perf_counter()
        page_reports: list[PageBaseline] = []
        total_blocks = 0
        scan_page_count = 0
        for signals in PdfReader(pdf_path).iter_signals():
            classification = self.classifier.classify(signals)
            if classification.kind.value != "scan_image":
                page_reports.append(
                    PageBaseline(page_index=signals.page_index, kind=classification.kind.value)
                )
                continue
            scan_page_count += 1
            start = time.perf_counter()
            image = renderer.render(signals.page_index, dpi=dpi)
            result = self.backend.recognize(image, OCROptions())
            blocks = result.blocks
            elapsed = time.perf_counter() - start
            total_blocks += len(blocks)
            page_reports.append(
                PageBaseline(
                    page_index=signals.page_index,
                    kind=classification.kind.value,
                    blocks=len(blocks),
                    characters=sum(len(block.text) for block in blocks),
                    low_confidence_blocks_lt_080=sum(
                        (block.confidence or 0.0) < 0.80 for block in blocks
                    ),
                    elapsed_seconds=round(elapsed, 3),
                )
            )
            del blocks, result, image
        return DocumentBaseline(
            file=pdf_path.name,
            page_count=len(page_reports),
            scan_page_count=scan_page_count,
            total_blocks=total_blocks,
            pages=tuple(page_reports),
            engine_id=self.backend.engine_id,
            dpi=dpi,
            elapsed_seconds=round(time.perf_counter() - started, 3),
            peak_rss_mb=round(peak_rss_mb(), 2),
        )
