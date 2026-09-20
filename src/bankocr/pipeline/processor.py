"""Connect PDF routing, rendering, OCR, parsing, and validation without retaining pages."""

from __future__ import annotations

from dataclasses import dataclass, replace
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Callable, Iterable

from bankocr.domain.coordinates import Point
from bankocr.domain.page import PageClassification, PageKind
from bankocr.image.preprocess import PagePreprocessor, PreprocessOptions
from bankocr.image.renderer import PdfRenderer
from bankocr.image.types import PageImage
from bankocr.ocr.backend import OCRBackend, OCROptions
from bankocr.ocr.rapidocr_backend import RapidOCRBackend
from bankocr.ocr.result import OCRPageResult
from bankocr.ocr.secondary import SecondaryOCR
from bankocr.parser.dispatch import GenericParser
from bankocr.parser.grid_recovery import GridCellRecovery
from bankocr.parser.known_templates import load_known_templates
from bankocr.parser.models import ParserOutcome, ParserOutcomeStatus
from bankocr.parser.templates import TableTemplate
from bankocr.pdf.classifier import PageClassifier
from bankocr.pdf.reader import PdfReader
from bankocr.pdf.native import NativeTextExtractor
from bankocr.pdf.native_quality import NativeTextQualityGate, deduplicate_blocks
from bankocr.pipeline.secondary_recovery import recover_validation_fields
from bankocr.validation.engine import TransactionValidator, ValidationReport


@dataclass(frozen=True, slots=True)
class PagePipelineResult:
    page_index: int
    classification: PageClassification
    ocr_result: OCRPageResult | None
    parser_outcome: ParserOutcome
    validation_report: ValidationReport | None


@dataclass(frozen=True, slots=True)
class DocumentPipelineResult:
    file: str
    pages: tuple[PagePipelineResult, ...]


class DocumentProcessor:
    def __init__(
        self,
        *,
        backend: OCRBackend | None = None,
        templates: tuple[TableTemplate, ...] | None = None,
        preprocessor: PagePreprocessor | None = None,
        classifier: PageClassifier | None = None,
        validator: TransactionValidator | None = None,
        secondary_ocr: SecondaryOCR | None = None,
        native_quality_gate: NativeTextQualityGate | None = None,
        template_dir: str | Path | None = None,
        reader_factory: Callable[[Path], PdfReader] = PdfReader,
        renderer_factory: Callable[[Path], PdfRenderer] = PdfRenderer,
    ) -> None:
        self.backend = backend or RapidOCRBackend()
        self.templates = templates or load_known_templates(template_dir)
        self.preprocessor = preprocessor or PagePreprocessor(
            PreprocessOptions(min_line_length_px=800)
        )
        self.classifier = classifier or PageClassifier()
        self.validator = validator or TransactionValidator()
        self.template_fingerprint = _fingerprint_templates(self.templates)
        self.validation_rules_fingerprint = hashlib.sha256(
            repr(self.validator.options).encode("utf-8")
        ).hexdigest()
        self.secondary_ocr = secondary_ocr or SecondaryOCR(
            self.backend,
            variants=("original", "upscale", "contrast", "adaptive", "line_removed"),
        )
        self.native_quality_gate = native_quality_gate or NativeTextQualityGate()
        self.reader_factory = reader_factory
        self.renderer_factory = renderer_factory

    def process(
        self,
        path: str | Path,
        *,
        dpi: int = 200,
        page_indexes: Iterable[int] | None = None,
        on_page: Callable[[PagePipelineResult], None] | None = None,
        temporary_template: TableTemplate | None = None,
    ) -> DocumentPipelineResult:
        pdf_path = Path(path)
        selected_pages = None if page_indexes is None else frozenset(page_indexes)
        renderer = self.renderer_factory(pdf_path)
        page_results: list[PagePipelineResult] = []

        def record(page_result: PagePipelineResult) -> None:
            # A callback is the streaming mode used by resumable projects. Do
            # not retain OCR blocks for every page in the returned document in
            # that mode; the caller receives and persists each page before the
            # next page is processed.
            if on_page is None:
                page_results.append(page_result)
            else:
                on_page(page_result)

        for signals in self.reader_factory(pdf_path).iter_signals():
            if selected_pages is not None and signals.page_index not in selected_pages:
                continue
            classification = self.classifier.classify(signals)
            if classification.kind is PageKind.NATIVE_TEXT:
                extractor = NativeTextExtractor(pdf_path)
                native_blocks = extractor.extract_page(signals.page_index)
                page_width, page_height = extractor.page_size(signals.page_index)
                quality = self.native_quality_gate.assess(
                    native_blocks,
                    page_width=page_width,
                    page_height=page_height,
                )
                if not quality.passed:
                    record(
                        self._process_image_page(
                            pdf_path,
                            renderer,
                            signals.page_index,
                            classification,
                            dpi=dpi,
                            native_blocks=(),
                            temporary_template=temporary_template,
                        )
                    )
                    continue
                parser = self._parser_for_page(
                    page_width,
                    temporary_template=temporary_template,
                )
                parser_outcome = parser.parse(native_blocks, page_height=page_height)
                validation_report = self._assess(
                    parser_outcome,
                    self.validator.validate(parser_outcome.candidates),
                )
                record(
                    PagePipelineResult(
                        page_index=signals.page_index,
                        classification=classification,
                        ocr_result=OCRPageResult(
                            signals.page_index,
                            native_blocks,
                            extractor.engine_id,
                        ),
                        parser_outcome=parser_outcome,
                        validation_report=validation_report,
                    )
                )
                continue
            if classification.kind not in (PageKind.SCAN_IMAGE, PageKind.HYBRID):
                failed_outcome = ParserOutcome.failed(
                    f"page kind {classification.kind.value} is not an OCR input"
                )
                record(
                    PagePipelineResult(
                        page_index=signals.page_index,
                        classification=classification,
                        ocr_result=None,
                        parser_outcome=failed_outcome,
                        validation_report=self._assess(
                            failed_outcome,
                            self.validator.validate(()),
                            page_error=classification.error,
                        ),
                    )
                )
                continue

            native_blocks: tuple = ()
            if classification.kind is PageKind.HYBRID:
                extractor = NativeTextExtractor(pdf_path)
                native_blocks_candidate = extractor.extract_page(signals.page_index)
                page_width, page_height = extractor.page_size(signals.page_index)
                quality = self.native_quality_gate.assess(
                    native_blocks_candidate,
                    page_width=page_width,
                    page_height=page_height,
                )
                if quality.passed:
                    native_blocks = native_blocks_candidate
            try:
                page_result = self._process_image_page(
                    pdf_path,
                    renderer,
                    signals.page_index,
                    classification,
                    dpi=dpi,
                    native_blocks=native_blocks,
                    temporary_template=temporary_template,
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                failed = ParserOutcome.failed(f"page processing failed: {error}")
                page_result = PagePipelineResult(
                    page_index=signals.page_index,
                    classification=PageClassification(signals.page_index, PageKind.PAGE_ERROR, error),
                    ocr_result=None,
                    parser_outcome=failed,
                    validation_report=self._assess(
                        failed,
                        self.validator.validate(()),
                        page_error=error,
                    ),
                )
            record(page_result)

        if on_page is None and page_results:
            all_candidates = tuple(
                candidate
                for page in page_results
                for candidate in page.parser_outcome.candidates
            )
            reports = self.validator.validate_document(
                all_candidates,
                blocks_by_page={
                    page.page_index: page.ocr_result.blocks
                    for page in page_results
                    if page.ocr_result is not None
                },
            )
            page_results = [
                replace(
                    page,
                    validation_report=self._assess(
                        page.parser_outcome,
                        reports.get(
                            page.page_index,
                            self.validator.validate(()),
                        ),
                    ),
                )
                for page in page_results
            ]

        return DocumentPipelineResult(file=pdf_path.name, pages=tuple(page_results))

    def _process_image_page(
        self,
        pdf_path: Path,
        renderer: PdfRenderer,
        page_index: int,
        classification: PageClassification,
        *,
        dpi: int,
        native_blocks: tuple | None = None,
        temporary_template: TableTemplate | None = None,
    ) -> PagePipelineResult:
        image = renderer.render(page_index, dpi=dpi)
        pdf_points = tuple(
            image.transform.to_pdf(point)
            for point in (
                Point(0.0, 0.0),
                Point(float(image.width_px), 0.0),
                Point(0.0, float(image.height_px)),
                Point(float(image.width_px), float(image.height_px)),
            )
        )
        page_width = max(point.x for point in pdf_points) - min(point.x for point in pdf_points)
        page_height = max(point.y for point in pdf_points) - min(point.y for point in pdf_points)
        preprocessed = self.preprocessor.process(image)
        processed_height, processed_width = preprocessed.ocr_image.shape[:2]
        ocr_image = PageImage(
            page_index=image.page_index,
            width_px=processed_width,
            height_px=processed_height,
            dpi=image.dpi,
            payload=preprocessed.ocr_image,
            transform=preprocessed.transform,
        )
        ocr_result = self.backend.recognize(ocr_image, OCROptions())
        if native_blocks:
            ocr_result = OCRPageResult(
                page_index=page_index,
                blocks=deduplicate_blocks(tuple(native_blocks) + ocr_result.blocks),
                engine_id=f"hybrid:{ocr_result.engine_id}",
            )
        parser = self._parser_for_page(
            page_width,
            temporary_template=temporary_template,
        )
        parser_outcome = parser.parse(
            ocr_result.blocks,
            page_height=page_height,
            horizontal_boundaries=preprocessed.horizontal_boundaries_pdf,
        )
        match = parser.matcher.match(ocr_result.blocks, page_height=page_height)
        if (
            parser_outcome.status is ParserOutcomeStatus.FAILED
            and match is not None
            and len(preprocessed.horizontal_boundaries_pdf) >= 2
        ):
            template = next(template for template in parser.templates if template.template_id == match.template_id)
            if template.row_strategy == "grid":
                parser_outcome = GridCellRecovery(self.secondary_ocr).parse(
                    ocr_image,
                    template,
                    page_width=page_width,
                    horizontal_boundaries=preprocessed.horizontal_boundaries_pdf,
                )
        initial_report = self.validator.validate(parser_outcome.candidates)
        parser_outcome = recover_validation_fields(
            ocr_image,
            ocr_result.blocks,
            parser_outcome,
            initial_report,
            self.secondary_ocr,
        )
        validation_report = self._assess(
            parser_outcome,
            self.validator.validate(parser_outcome.candidates),
        )
        return PagePipelineResult(
            page_index=page_index,
            classification=classification,
            ocr_result=ocr_result,
            parser_outcome=parser_outcome,
            validation_report=validation_report,
        )

    def _parser_for_page(
        self,
        page_width: float,
        *,
        temporary_template: TableTemplate | None,
    ) -> GenericParser:
        # A confirmed temporary template is deliberately exclusive.  Falling
        # back silently to a formal template would make a reviewer believe
        # the confirmed mapping was used when it was not.
        templates = (temporary_template,) if temporary_template is not None else self.templates
        return GenericParser(templates, page_width=page_width)

    def _assess(
        self,
        outcome: ParserOutcome,
        report: ValidationReport,
        *,
        page_error: str | None = None,
    ) -> ValidationReport:
        return self.validator.assess(
            report,
            outcome.candidates,
            parser_status=outcome.status,
            page_error=page_error or outcome.reason if outcome.status is ParserOutcomeStatus.FAILED else page_error,
        )


def _fingerprint_templates(templates: tuple[TableTemplate, ...]) -> str:
    payload = json.dumps(
        [asdict(template) for template in templates],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
