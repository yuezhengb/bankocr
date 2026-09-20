"""Launch the optional offline review UI for a persisted run."""

from __future__ import annotations

import argparse
from pathlib import Path

from bankocr.gui.app import run_persisted_review
from bankocr.storage.project_store import ProjectStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review a persisted BankOCR run")
    parser.add_argument("--project-db", type=Path, required=True)
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args(argv)
    if not args.project_db.is_file():
        parser.error(f"project database does not exist: {args.project_db}")
    with ProjectStore(args.project_db) as store:
        return run_persisted_review(store, args.run_id)


if __name__ == "__main__":
    raise SystemExit(main())
