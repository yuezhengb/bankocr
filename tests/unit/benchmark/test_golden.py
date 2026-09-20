import json

import pytest

from bankocr.benchmark.golden import load_golden_sample


def test_load_golden_sample_keeps_transaction_keys_and_field_values(tmp_path) -> None:
    path = tmp_path / "truth.json"
    path.write_text(
        json.dumps(
            {
                "sample_id": "synthetic-grid-v1",
                "transactions": [
                    {
                        "page_index": 0,
                        "row_index": 2,
                        "fields": {"date": "2026-01-02", "amount": "12.30"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    sample = load_golden_sample(path)

    assert sample.sample_id == "synthetic-grid-v1"
    assert sample.truths[0].page_index == 0
    assert sample.truths[0].row_index == 2
    assert sample.truths[0].fields == {"date": "2026-01-02", "amount": "12.30"}


def test_load_golden_sample_rejects_duplicate_page_and_row_keys(tmp_path) -> None:
    path = tmp_path / "truth.json"
    path.write_text(
        json.dumps(
            {
                "sample_id": "duplicate",
                "transactions": [
                    {"page_index": 0, "row_index": 1, "fields": {"amount": "1.00"}},
                    {"page_index": 0, "row_index": 1, "fields": {"amount": "2.00"}},
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate truth key"):
        load_golden_sample(path)


def test_load_golden_sample_rejects_non_string_field_values(tmp_path) -> None:
    path = tmp_path / "truth.json"
    path.write_text(
        json.dumps(
            {
                "sample_id": "invalid",
                "transactions": [
                    {"page_index": 0, "row_index": 1, "fields": {"amount": 1.0}},
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="field values must be strings"):
        load_golden_sample(path)
