from pathlib import Path

from bankocr.domain.coordinates import Point
from bankocr.domain.run_manifest import RunManifest
from bankocr.domain.text_block import SourceSpan, SourceType, TextBlock
from bankocr.ocr.result import OCRPageResult
from bankocr.parser.models import FieldValue, TransactionCandidate
from bankocr.storage.project_store import ProjectStore


def _manifest() -> RunManifest:
    return RunManifest(
        app_version="0.1.0",
        project_schema_version="1",
        ocr_engine="rapidocr",
        ocr_model_id="PP-OCRv6-small",
        model_sha256="a" * 64,
        execution_provider="CPUExecutionProvider",
        preprocess_profile="default-v1",
        parser_version="parser-v1",
        template_version="template-v1",
        validation_rules_version="rules-v1",
        exporter_version="export-v1",
    )


def test_project_store_round_trips_text_block_ids_and_field_source_spans(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")
    run_id = store.create_run(project_id, _manifest())
    block = TextBlock(
        text="交易摘要",
        raw_text="交易摘要",
        polygon=(Point(1, 2), Point(20, 2), Point(20, 10), Point(1, 10)),
        confidence=0.91,
        source_type=SourceType.OCR,
        page_index=0,
        engine_id="test",
        text_block_id="p000:ocr:0001",
    )
    field = FieldValue(
        "交易摘要",
        "交易摘要",
        source_block_indices=(0,),
        source_spans=(SourceSpan.from_block(block),),
    )
    candidate = TransactionCandidate(
        page_index=0,
        row_index=0,
        parser_id="test:v1",
        fields={"summary": field},
    )

    store.save_page_result(
        run_id,
        0,
        (candidate,),
        OCRPageResult(0, (block,), "test"),
        None,
        "completed",
    )
    store.close()

    reopened = ProjectStore(tmp_path / "project.sqlite3")
    loaded_block = reopened.load_ocr_blocks(run_id)[0][0]
    loaded_field = reopened.load_candidates(run_id)[0].field("summary")
    assert loaded_block.text_block_id == "p000:ocr:0001"
    assert loaded_field.source_spans[0].text_block_id == "p000:ocr:0001"
    assert loaded_field.source_spans[0].polygon == block.polygon
    reopened.close()
