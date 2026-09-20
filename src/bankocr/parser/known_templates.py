"""Versioned templates for two published statement layouts (geometry only)."""

from __future__ import annotations

from pathlib import Path
import sys

from .template_pack import TemplatePack
from .templates import ColumnDefinition, TableTemplate


def load_known_templates(template_dir: str | Path | None = None) -> tuple[TableTemplate, ...]:
    """Load the declarative pack when present, with a built-in fallback.

    The fallback keeps the Python package importable in minimal environments;
    normal repository and release runs use ``templates/known/*.json`` so
    template changes remain data changes rather than parser-code changes.
    """

    directory = Path(template_dir) if template_dir is not None else _default_template_dir()
    if directory.is_dir():
        manifest = directory.parent / "manifest.json"
        pack = TemplatePack.from_directory(
            directory,
            manifest_path=manifest if manifest.is_file() else None,
        )
        return pack.templates
    if template_dir is not None:
        raise FileNotFoundError(f"template directory does not exist: {directory}")
    return (bohai_detail_template(), online_statement_template())


def _default_template_dir() -> Path:
    candidates = [
        Path(__file__).resolve().parents[3] / "templates" / "known",
        Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "templates" / "known",
        Path(sys.executable).resolve().parent / "templates" / "known",
    ]
    return next((path for path in candidates if path.is_dir()), candidates[0])


def bohai_detail_template() -> TableTemplate:
    """Grid-style detail statement layout (column geometry only)."""

    return TableTemplate(
        template_id="bohai_detail_v1",
        version="1",
        header_tokens=(
            "交易日期",
            "交易金额",
            "余额",
            "交易渠道",
            "摘要码描述",
            "对方账号",
            "对方名称",
            "交易时间",
        ),
        columns=(
            ColumnDefinition("transaction_date", 0.032, 0.143),
            ColumnDefinition("transaction_amount", 0.143, 0.255),
            ColumnDefinition("balance", 0.255, 0.385),
            ColumnDefinition("channel", 0.385, 0.496),
            ColumnDefinition("description", 0.496, 0.607),
            ColumnDefinition("counterparty_account", 0.607, 0.701),
            ColumnDefinition("counterparty_name", 0.701, 0.887),
            ColumnDefinition("transaction_time", 0.887, 0.979),
        ),
        required_fields=("transaction_date", "transaction_amount", "balance"),
        row_strategy="grid",
    )


def online_statement_template() -> TableTemplate:
    """Anchor-date online statement layout (column geometry only)."""

    return TableTemplate(
        template_id="online_statement_v1",
        version="1",
        header_tokens=(
            "记账日期",
            "币种",
            "收入金额",
            "支出金额",
            "联机余额",
            "交易摘要",
            "交易对手信息",
            "客户摘要",
        ),
        columns=(
            ColumnDefinition("accounting_date", 0.034, 0.101),
            ColumnDefinition("currency", 0.101, 0.195),
            ColumnDefinition("income_amount", 0.195, 0.309),
            ColumnDefinition("expense_amount", 0.309, 0.413),
            ColumnDefinition("online_balance", 0.413, 0.520),
            ColumnDefinition("transaction_summary", 0.520, 0.654),
            ColumnDefinition("counterparty_info", 0.654, 0.832),
            ColumnDefinition("customer_summary", 0.832, 0.980),
        ),
        required_fields=("accounting_date", "currency", "online_balance"),
        row_strategy="anchor_date",
    )
