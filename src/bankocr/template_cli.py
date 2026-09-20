"""Confirm a run-scoped Temporary Template from an explicit column mapping."""

from __future__ import annotations

import argparse
from pathlib import Path

from bankocr.parser.templates import ColumnDefinition
from bankocr.parser.temporary_template import TemporaryTemplateConfirmation
from bankocr.storage.project_store import ProjectStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Save a confirmed offline Temporary Template for one BankOCR run"
    )
    parser.add_argument("--project-db", type=Path, required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--source-page", type=int, required=True)
    parser.add_argument(
        "--headers",
        required=True,
        help="comma-separated header tokens in left-to-right order",
    )
    parser.add_argument(
        "--columns",
        required=True,
        help="semicolon-separated name:left_ratio:right_ratio definitions",
    )
    parser.add_argument("--required-fields", required=True, help="comma-separated required fields")
    parser.add_argument("--reviewer", default="local-user")
    parser.add_argument("--row-strategy", choices=("grid", "anchor_date", "positional"), default="anchor_date")
    parser.add_argument("--header-y-ratio", type=float, default=0.30)
    parser.add_argument("--version", default="temporary-v1")
    args = parser.parse_args(argv)
    if not args.project_db.is_file():
        parser.error(f"project database does not exist: {args.project_db}")
    try:
        columns = tuple(_parse_column(item) for item in args.columns.split(";"))
        confirmation = TemporaryTemplateConfirmation(
            run_id=args.run_id,
            source_page_index=args.source_page,
            header_tokens=_split_values(args.headers),
            columns=columns,
            required_fields=_split_values(args.required_fields),
            confirmed_by=args.reviewer,
            row_strategy=args.row_strategy,
            header_y_ratio=args.header_y_ratio,
            version=args.version,
        )
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))
    with ProjectStore(args.project_db) as store:
        store.save_temporary_template(confirmation.to_record())
        # A mapping confirmation is an explicit request to retry PAGE_REVIEW
        # pages.  The normal resume command remains conservative by default.
        store.requeue_review_pages(args.run_id)
    print(
        f"temporary template saved: run={args.run_id}, "
        f"template={confirmation.template_id}, source_page={args.source_page}"
    )
    return 0


def _split_values(value: str) -> tuple[str, ...]:
    values = tuple(item.strip() for item in value.split(",") if item.strip())
    if not values:
        raise ValueError("a comma-separated value must not be empty")
    return values


def _parse_column(value: str) -> ColumnDefinition:
    parts = tuple(part.strip() for part in value.split(":"))
    if len(parts) != 3:
        raise ValueError(
            f"invalid column {value!r}; expected name:left_ratio:right_ratio"
        )
    try:
        return ColumnDefinition(parts[0], float(parts[1]), float(parts[2]))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid column {value!r}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
