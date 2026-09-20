import pytest

from bankocr.domain.coordinates import Point
from bankocr.domain.text_block import SourceSpan
from bankocr.gui.review_model import ReviewSession
from bankocr.parser.models import FieldValue, TransactionCandidate


def _candidate(row: int) -> TransactionCandidate:
    return TransactionCandidate(
        page_index=0,
        row_index=row,
        parser_id="test:v1",
        fields={
            "amount": FieldValue(
                "1O.00",
                "10.00",
                source_block_indices=(row,),
                source_spans=(
                    SourceSpan(
                        page_index=0,
                        polygon=(Point(float(row), 0.0), Point(float(row + 1), 1.0)),
                        text_block_id=f"block-{row}",
                    ),
                ),
            ),
        },
    )


def test_review_session_keeps_edits_in_final_layer_only() -> None:
    session = ReviewSession((_candidate(0), _candidate(1)))

    edited = session.edit_field(0, "amount", "11.00")
    accepted = edited.accept(0)

    assert edited.candidates[0].field("amount").raw_text == "1O.00"
    assert edited.candidates[0].field("amount").suggested_text == "10.00"
    assert edited.candidates[0].field("amount").final_text is None
    assert accepted.candidates[0].field("amount").final_text == "11.00"
    assert accepted.pending_count == 1
    assert accepted.edits == ()


def test_review_session_drops_edits_when_candidate_is_rejected() -> None:
    session = ReviewSession((_candidate(0),)).edit_field(0, "amount", "11.00")

    rejected = session.reject(0)

    assert rejected.candidates[0].status.value == "rejected"
    assert rejected.edits == ()


def test_review_session_rejects_invalid_indexes() -> None:
    session = ReviewSession((_candidate(0),))

    try:
        session.accept(2)
    except IndexError:
        pass
    else:
        raise AssertionError("expected invalid row index to fail")


def test_persisted_review_saves_the_final_candidate_layers(tmp_path, monkeypatch) -> None:
    from bankocr.domain.run_manifest import RunManifest
    from bankocr.gui import app
    from bankocr.storage.project_store import ProjectStore

    manifest = RunManifest(
        app_version="0.1.0",
        project_schema_version="1",
        ocr_engine="test",
        ocr_model_id="test",
        model_sha256="a" * 64,
        execution_provider="cpu",
        preprocess_profile="test",
        parser_version="test",
        template_version="test",
        validation_rules_version="test",
        exporter_version="test",
    )
    store = ProjectStore(tmp_path / "project.sqlite3")
    project_id = store.create_project("demo", "statement.pdf")
    run_id = store.create_run(project_id, manifest)
    candidate = TransactionCandidate(
        page_index=0,
        row_index=0,
        parser_id="test:v1",
        fields={
            "transaction_date": FieldValue("2026-08-01", "2026-08-01"),
            "transaction_amount": FieldValue("1.00", "1.00"),
            "balance": FieldValue("1.00", "1.00"),
        },
    )
    store.save_candidates(run_id, (candidate,))
    store.save_page_state(run_id, 0, "needs_review")
    store.set_run_status(run_id, "needs_review")

    def fake_run_review(candidates, *, on_save, **kwargs):
        assert tuple(candidates) == (candidate,)
        assert kwargs["source_pdf"] == app.Path("statement.pdf")
        on_save((candidate.accept(),))
        return 0

    monkeypatch.setattr(app, "run_review", fake_run_review)

    assert app.run_persisted_review(store, run_id) == 0
    assert store.load_candidates(run_id)[0].status.value == "accepted"
    assert store.get_run_status(run_id) == "completed"
    store.close()


def test_move_candidate_records_order_without_changing_source_identity() -> None:
    session = ReviewSession((_candidate(0), _candidate(1), _candidate(2)))

    moved = session.move_candidate(0, 2)

    assert tuple(candidate.row_index for candidate in moved.candidates) == (1, 2, 0)
    assert tuple(candidate.review_order for candidate in moved.candidates) == (0, 1, 2)
    assert moved.candidates[-1].field("amount").source_spans[0].text_block_id == "block-0"
    assert moved.operations[-1].action == "move"


def test_merge_preserves_all_field_provenance_and_requires_review() -> None:
    first = _candidate(0)
    second = _candidate(1)
    session = ReviewSession((first, second))

    merged = session.merge_candidates(0, 1)

    assert len(merged.candidates) == 1
    candidate = merged.candidates[0]
    assert candidate.status.value == "unreviewed"
    assert candidate.row_index == 0
    assert candidate.field("amount").raw_text == "1O.00 | 1O.00"
    assert candidate.field("amount").source_block_indices == (0, 1)
    assert tuple(span.text_block_id for span in candidate.field("amount").source_spans) == (
        "block-0",
        "block-1",
    )
    assert merged.operations[-1].action == "merge"


def test_split_moves_selected_fields_into_new_row_and_keeps_provenance() -> None:
    candidate = TransactionCandidate(
        page_index=0,
        row_index=4,
        parser_id="test:v1",
        fields={
            "amount": FieldValue("10.00", "10.00", source_block_indices=(1,)),
            "description": FieldValue("rent", "rent", source_block_indices=(2,)),
        },
        status="accepted",
    )

    split = ReviewSession((candidate,)).split_candidate(0, ("description",))

    assert len(split.candidates) == 2
    assert set(dict(split.candidates[0].fields)) == {"amount"}
    assert set(dict(split.candidates[1].fields)) == {"description"}
    assert all(item.status.value == "unreviewed" for item in split.candidates)
    assert split.candidates[1].row_index == 5
    assert split.operations[-1].action == "split"


def test_add_missing_candidate_allocates_new_row_identity_and_mark_duplicate() -> None:
    added = ReviewSession((_candidate(0),)).add_candidate(_candidate(0))

    assert tuple(item.row_index for item in added.candidates) == (0, 1)
    duplicate = added.mark_duplicate(1, 0)

    assert duplicate.candidates[1].status.value == "duplicate"
    assert duplicate.candidates[1].duplicate_of == (0, 0)
    assert duplicate.operations[-1].action == "mark_duplicate"
    assert duplicate.pending_count == 1


@pytest.mark.parametrize(
    "operation",
    [
        lambda session: session.merge_candidates(0, 1),
        lambda session: session.split_candidate(0, ("missing",)),
        lambda session: session.mark_duplicate(0, 0),
    ],
)
def test_structure_operations_fail_closed(operation) -> None:
    with pytest.raises((ValueError, KeyError, IndexError)):
        operation(ReviewSession((_candidate(0),)))
