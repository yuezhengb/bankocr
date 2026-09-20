"""Known table templates and a conservative wired-column parser."""

from __future__ import annotations

from dataclasses import dataclass
import unicodedata
from typing import Literal

from .models import FieldValue, ParserOutcome, TransactionCandidate
from .rows import RowGroupingOptions, RowGroup, group_text_blocks
from .suggestions import suggest_outcome
from bankocr.domain.text_block import SourceSpan, TextBlock


RowStrategy = Literal["grid", "anchor_date", "positional"]


@dataclass(frozen=True, slots=True)
class ColumnDefinition:
    name: str
    left_ratio: float
    right_ratio: float

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("column name must not be empty")
        if not 0.0 <= self.left_ratio < self.right_ratio <= 1.0:
            raise ValueError("column ratios must satisfy 0 <= left < right <= 1")

    def contains(self, x_ratio: float) -> bool:
        return self.left_ratio <= x_ratio < self.right_ratio


@dataclass(frozen=True, slots=True)
class TableTemplate:
    template_id: str
    version: str
    header_tokens: tuple[str, ...]
    columns: tuple[ColumnDefinition, ...]
    required_fields: tuple[str, ...]
    row_strategy: RowStrategy = "grid"
    header_y_ratio: float = 0.25

    def __post_init__(self) -> None:
        if not self.template_id or not self.version:
            raise ValueError("template_id and version must not be empty")
        if not self.header_tokens or any(not token for token in self.header_tokens):
            raise ValueError("at least one non-empty header token is required")
        if not self.columns:
            raise ValueError("at least one column is required")
        if self.row_strategy not in ("grid", "anchor_date", "positional"):
            raise ValueError("row_strategy must be grid, anchor_date, or positional")
        if not 0.0 < self.header_y_ratio <= 1.0:
            raise ValueError("header_y_ratio must be between 0 and 1")
        names = tuple(column.name for column in self.columns)
        if len(set(names)) != len(names):
            raise ValueError("column names must be unique")
        if any(name not in names for name in self.required_fields):
            raise ValueError("required field must refer to a declared column")


@dataclass(frozen=True, slots=True)
class TemplateMatch:
    template_id: str
    score: float
    matched_tokens: tuple[str, ...]


class TemplateMatcher:
    def __init__(
        self,
        templates: tuple[TableTemplate, ...],
        *,
        minimum_header_score: float = 0.6,
    ) -> None:
        if not templates:
            raise ValueError("at least one table template is required")
        if not 0.0 < minimum_header_score <= 1.0:
            raise ValueError("minimum_header_score must be between 0 and 1")
        self.templates = templates
        self.minimum_header_score = minimum_header_score

    def match(
        self,
        blocks: tuple[TextBlock, ...] | list[TextBlock],
        *,
        page_height: float | None = None,
    ) -> TemplateMatch | None:
        if page_height is not None and page_height <= 0:
            raise ValueError("page_height must be positive")
        candidates: list[TemplateMatch] = []
        for template in self.templates:
            candidate_blocks = blocks
            if page_height is not None:
                header_limit = page_height * template.header_y_ratio
                candidate_blocks = tuple(block for block in blocks if block.bbox[1] <= header_limit)
            haystack = "".join(_normalize_token(block.text) for block in candidate_blocks)
            matched = tuple(
                token
                for token in template.header_tokens
                if _normalize_token(token) in haystack
            )
            score = len(matched) / len(template.header_tokens)
            if score >= self.minimum_header_score:
                candidates.append(TemplateMatch(template.template_id, score, matched))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item.score, reverse=True)
        if len(candidates) > 1 and candidates[0].score == candidates[1].score:
            return None
        return candidates[0]


class WiredTableParser:
    """Parse rows only after a trusted template has fixed every column boundary."""

    def __init__(
        self,
        template: TableTemplate,
        *,
        page_width: float,
        row_options: RowGroupingOptions | None = None,
    ) -> None:
        if page_width <= 0:
            raise ValueError("page_width must be positive")
        self.template = template
        self.page_width = page_width
        self.row_options = row_options or RowGroupingOptions()

    def parse(self, blocks: tuple[TextBlock, ...] | list[TextBlock]) -> ParserOutcome:
        source_indexes = {id(block): index for index, block in enumerate(blocks)}
        rows = group_text_blocks(blocks, self.row_options)
        candidates: list[TransactionCandidate] = []
        for row_index, row in enumerate(rows):
            if self._is_header_row(row):
                continue
            fields = self._parse_row(row, source_indexes)
            if not fields:
                continue
            missing = [name for name in self.template.required_fields if name not in fields]
            if missing:
                return ParserOutcome.failed(
                    f"row {row_index} is missing required fields: {', '.join(missing)}"
                )
            candidates.append(
                TransactionCandidate(
                    page_index=row.blocks[0].page_index,
                    row_index=row_index,
                    parser_id=self.template.template_id,
                    fields=fields,
                )
            )
        if not candidates:
            return ParserOutcome.failed("no transaction rows matched the trusted template")
        return suggest_outcome(ParserOutcome.success(tuple(candidates)))

    def _parse_row(self, row: RowGroup, source_indexes: dict[int, int]) -> dict[str, FieldValue]:
        return _fields_from_blocks(self.template, row.blocks, self.page_width, source_indexes)

    def _is_header_row(self, row: RowGroup) -> bool:
        text = "".join(_normalize_token(block.text) for block in row.blocks)
        matches = sum(_normalize_token(token) in text for token in self.template.header_tokens)
        return matches >= max(1, len(self.template.header_tokens) // 2)


def _normalize_token(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    return "".join(
        character
        for character in normalized
        if character.isalnum() or "\u3400" <= character <= "\u9fff"
    ).casefold()


def _fields_from_blocks(
    template: TableTemplate,
    blocks: tuple[TextBlock, ...],
    page_width: float,
    source_indexes: dict[int, int],
) -> dict[str, FieldValue]:
    cells: dict[str, list[TextBlock]] = {}
    for block in blocks:
        x_center = (block.bbox[0] + block.bbox[2]) / 2.0
        x_ratio = x_center / page_width
        for column in template.columns:
            if column.contains(x_ratio):
                cells.setdefault(column.name, []).append(block)
                break

    fields: dict[str, FieldValue] = {}
    for name, cell_blocks in cells.items():
        texts = tuple(block.text.strip() for block in cell_blocks if block.text.strip())
        if not texts:
            continue
        confidence_values = tuple(
            block.confidence for block in cell_blocks if block.confidence is not None
        )
        confidence = min(confidence_values) if confidence_values else None
        fields[name] = FieldValue(
            raw_text=" ".join(texts),
            suggested_text=" ".join(texts),
            confidence=confidence,
            source_block_indices=tuple(sorted(source_indexes[id(block)] for block in cell_blocks)),
            source_spans=tuple(SourceSpan.from_block(block) for block in cell_blocks),
        )
    return fields
