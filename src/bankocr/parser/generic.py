"""Conservative layout inference for previously unseen statement formats."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import unicodedata

from bankocr.domain.text_block import TextBlock

from .anchor import AnchorDateParser
from .models import ParserOutcome
from .templates import ColumnDefinition, TableTemplate


_ALIASES: dict[str, tuple[str, ...]] = {
    "accounting_date": ("记账日期", "交易日期", "日期", "date", "交易日"),
    "currency": ("币种", "货币", "currency"),
    "income_amount": ("收入金额", "收入", "贷方", "存入", "credit"),
    "expense_amount": ("支出金额", "支出", "借方", "取出", "debit"),
    "transaction_amount": ("交易金额", "发生额", "金额", "amount"),
    "balance": ("联机余额", "账户余额", "可用余额", "余额", "balance"),
    "transaction_summary": ("交易摘要", "摘要", "用途", "备注", "description"),
    "counterparty_account": ("对方账号", "对手账号", "收款账号", "付款账号", "account"),
    "counterparty_name": ("对方名称", "对手名称", "对方户名", "户名", "name"),
}


@dataclass(frozen=True, slots=True)
class GenericInference:
    template: TableTemplate | None
    reason: str | None = None


class GenericLayoutParser:
    """Infer only unambiguous columns; everything else becomes PAGE_REVIEW."""

    def __init__(self, *, page_width: float) -> None:
        if page_width <= 0:
            raise ValueError("page_width must be positive")
        self.page_width = page_width

    def infer(
        self,
        blocks: tuple[TextBlock, ...] | list[TextBlock],
        *,
        page_height: float | None = None,
    ) -> GenericInference:
        if not blocks:
            return GenericInference(None, "generic parser received no OCR blocks")
        header_blocks = self._header_blocks(blocks, page_height)
        detections: dict[str, list[tuple[TextBlock, str]]] = {}
        for block in header_blocks:
            normalized = _normalize(block.text)
            matches = [
                (len(_normalize(alias)), field_name, alias)
                for field_name, aliases in _ALIASES.items()
                for alias in aliases
                if _normalize(alias) in normalized
            ]
            if matches:
                best_length = max(match[0] for match in matches)
                for _, field_name, alias in matches:
                    if len(_normalize(alias)) == best_length:
                        detections.setdefault(field_name, []).append((block, alias))

        for field_name, candidates in detections.items():
            if len(candidates) > 1:
                return GenericInference(
                    None,
                    f"generic {field_name} column is ambiguous ({len(candidates)} headers)",
                )

        date = _single(detections, "accounting_date")
        balance = _single(detections, "balance")
        amount_fields = tuple(
            field_name
            for field_name in ("transaction_amount", "income_amount", "expense_amount")
            if field_name in detections
        )
        if date is None or balance is None:
            return GenericInference(None, "generic parser could not identify one date and one balance column")
        if not amount_fields:
            return GenericInference(None, "generic parser could not identify an amount column")

        selected = [("accounting_date", date[0]), ("balance", balance[0])]
        selected.extend((field_name, _single(detections, field_name)[0]) for field_name in amount_fields)
        for field_name in ("currency", "transaction_summary", "counterparty_account", "counterparty_name"):
            value = _single(detections, field_name)
            if value is not None:
                selected.append((field_name, value[0]))
        selected.sort(key=lambda item: ((item[1].bbox[0] + item[1].bbox[2]) / 2.0, item[0]))

        centers = [((block.bbox[0] + block.bbox[2]) / 2.0) for _, block in selected]
        if any(right <= left for left, right in zip(centers, centers[1:])):
            return GenericInference(None, "generic header columns overlap")
        edges = [0.0]
        edges.extend((left + right) / 2.0 / self.page_width for left, right in zip(centers, centers[1:]))
        edges.append(1.0)
        columns = tuple(
            ColumnDefinition(field_name, edges[index], edges[index + 1])
            for index, (field_name, _) in enumerate(selected)
        )
        token_text = "|".join(block.text for _, block in selected)
        template_id = "generic:" + hashlib.sha1(token_text.encode("utf-8")).hexdigest()[:12]
        return GenericInference(
            TableTemplate(
                template_id=template_id,
                version="1",
                header_tokens=tuple(block.text for _, block in selected),
                columns=columns,
                required_fields=("accounting_date", "balance"),
                row_strategy="anchor_date",
                header_y_ratio=0.30,
            )
        )

    def parse(
        self,
        blocks: tuple[TextBlock, ...] | list[TextBlock],
        *,
        page_height: float | None = None,
    ) -> ParserOutcome:
        inference = self.infer(blocks, page_height=page_height)
        if inference.template is None:
            reason = inference.reason or "generic parser could not infer a layout"
            return ParserOutcome.page_review(
                f"no trusted template matched the page; confirm columns: {reason}"
            )
        return AnchorDateParser(inference.template, page_width=self.page_width).parse(blocks)

    @staticmethod
    def _header_blocks(
        blocks: tuple[TextBlock, ...] | list[TextBlock],
        page_height: float | None,
    ) -> tuple[TextBlock, ...]:
        if page_height is not None and page_height > 0:
            limit = page_height * 0.30
        else:
            minimum = min(block.bbox[1] for block in blocks)
            maximum = max(block.bbox[3] for block in blocks)
            limit = minimum + max(40.0, (maximum - minimum) * 0.25)
        return tuple(block for block in blocks if block.bbox[1] <= limit)


def _single(
    detections: dict[str, list[tuple[TextBlock, str]]],
    field_name: str,
) -> tuple[TextBlock, str] | None:
    values = detections.get(field_name, [])
    return values[0] if len(values) == 1 else None


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", normalized)
