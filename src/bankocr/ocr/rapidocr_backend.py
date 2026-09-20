"""RapidOCR adapter that emits the project-wide OCR result contract."""

from __future__ import annotations

import inspect
from typing import Any
from pathlib import Path

from bankocr.domain.coordinates import Point
from bankocr.domain.text_block import SourceType, TextBlock
from bankocr.image.types import PageImage
from bankocr.ocr.backend import OCROptions
from bankocr.ocr.result import OCRPageResult
from bankocr.ocr.model_pack import ModelPack


class RapidOCRBackend:
    engine_id = "rapidocr:pp-ocrv6-small:onnxruntime-cpu"

    def __init__(self, engine: Any | None = None, model_pack: ModelPack | None = None) -> None:
        if engine is None:
            from rapidocr import RapidOCR

            if model_pack is None:
                import rapidocr

                model_pack = ModelPack.from_directory(Path(rapidocr.__file__).parent / "models")
            engine = RapidOCR(params=model_pack.rapidocr_params())
        self._engine = engine
        self.model_pack = model_pack

    def recognize(self, image: PageImage, options: OCROptions) -> OCRPageResult:
        output = self._call_engine(image.payload, options)
        boxes = getattr(output, "boxes", None)
        texts = tuple(getattr(output, "txts", ()) or ())
        scores = tuple(getattr(output, "scores", ()) or ())
        if boxes is None:
            boxes = ()
        if len(boxes) != len(texts) or len(texts) != len(scores):
            raise ValueError("RapidOCR output boxes, texts, and scores must have equal lengths")

        blocks: list[TextBlock] = []
        for block_number, (box, text, score) in enumerate(zip(boxes, texts, scores)):
            score_value = float(score)
            if score_value < options.score_threshold:
                continue
            polygon = tuple(
                image.transform.to_pdf(Point(float(point[0]), float(point[1])))
                for point in box
            )
            blocks.append(
                TextBlock(
                    text=str(text),
                    raw_text=str(text),
                    polygon=polygon,
                    confidence=score_value,
                    source_type=SourceType.OCR,
                    page_index=image.page_index,
                    engine_id=self.engine_id,
                    text_block_id=f"p{image.page_index:04d}:ocr:{block_number:06d}",
                )
            )
        return OCRPageResult(
            page_index=image.page_index,
            blocks=tuple(blocks),
            engine_id=self.engine_id,
        )

    def _call_engine(self, payload: object, options: OCROptions) -> object:
        """Pass supported per-call options without coupling test backends."""

        try:
            parameters = inspect.signature(self._engine).parameters
        except (TypeError, ValueError):
            parameters = {}
        accepts_kwargs = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        if accepts_kwargs or {"use_cls", "text_score"}.intersection(parameters):
            return self._engine(
                payload,
                use_cls=options.detect_orientation,
                text_score=options.score_threshold,
            )
        return self._engine(payload)
