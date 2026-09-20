from bankocr.parser.known_templates import (
    bohai_detail_template,
    online_statement_template,
)


def test_known_statement_templates_capture_observed_columns_and_row_strategies() -> None:
    bohai = bohai_detail_template()
    online = online_statement_template()

    assert bohai.template_id == "bohai_detail_v1"
    assert bohai.row_strategy == "grid"
    assert tuple(column.name for column in bohai.columns) == (
        "transaction_date",
        "transaction_amount",
        "balance",
        "channel",
        "description",
        "counterparty_account",
        "counterparty_name",
        "transaction_time",
    )
    assert online.template_id == "online_statement_v1"
    assert online.row_strategy == "anchor_date"
    assert "income_amount" in tuple(column.name for column in online.columns)
    assert "expense_amount" in tuple(column.name for column in online.columns)
