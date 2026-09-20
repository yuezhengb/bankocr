"""Run-scoped templates confirmed during human review."""

from __future__ import annotations

from dataclasses import dataclass

from .templates import ColumnDefinition, RowStrategy, TableTemplate


@dataclass(frozen=True, slots=True)
class TemporaryTemplateRecord:
    run_id: int
    source_page_index: int
    template: TableTemplate
    confirmed_by: str
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        if self.run_id <= 0:
            raise ValueError("temporary template run_id must be positive")
        if self.source_page_index < 0:
            raise ValueError("temporary template source_page_index must be non-negative")
        if not self.confirmed_by.strip():
            raise ValueError("temporary template confirmed_by must not be empty")
        expected_id = f"temporary:run-{self.run_id}:page-{self.source_page_index}"
        if self.template.template_id != expected_id:
            raise ValueError(
                "temporary template id must match its run and source page: "
                f"{expected_id}"
            )


@dataclass(frozen=True, slots=True)
class TemporaryTemplateConfirmation:
    """The explicit column mapping a reviewer confirms for one Run."""

    run_id: int
    source_page_index: int
    header_tokens: tuple[str, ...]
    columns: tuple[ColumnDefinition, ...]
    required_fields: tuple[str, ...]
    confirmed_by: str = "local-user"
    row_strategy: RowStrategy = "anchor_date"
    header_y_ratio: float = 0.30
    version: str = "temporary-v1"

    def __post_init__(self) -> None:
        if self.run_id <= 0:
            raise ValueError("temporary template run_id must be positive")
        if self.source_page_index < 0:
            raise ValueError("temporary template source_page_index must be non-negative")
        if not self.confirmed_by.strip():
            raise ValueError("temporary template confirmed_by must not be empty")
        if not self.header_tokens or any(not token.strip() for token in self.header_tokens):
            raise ValueError("temporary template requires non-empty header tokens")
        if not self.columns:
            raise ValueError("temporary template requires at least one column")
        ordered = sorted(self.columns, key=lambda column: column.left_ratio)
        if any(left.right_ratio > right.left_ratio for left, right in zip(ordered, ordered[1:])):
            raise ValueError("temporary template columns must not overlap")
        if not self.required_fields:
            raise ValueError("temporary template requires at least one required field")
        if not 0.0 < self.header_y_ratio <= 1.0:
            raise ValueError("temporary template header_y_ratio must be between 0 and 1")
        if not self.version.strip():
            raise ValueError("temporary template version must not be empty")

    @property
    def template_id(self) -> str:
        return f"temporary:run-{self.run_id}:page-{self.source_page_index}"

    def to_record(self) -> TemporaryTemplateRecord:
        template = TableTemplate(
            template_id=self.template_id,
            version=self.version,
            header_tokens=self.header_tokens,
            columns=self.columns,
            required_fields=self.required_fields,
            row_strategy=self.row_strategy,
            header_y_ratio=self.header_y_ratio,
        )
        return TemporaryTemplateRecord(
            run_id=self.run_id,
            source_page_index=self.source_page_index,
            template=template,
            confirmed_by=self.confirmed_by,
        )
