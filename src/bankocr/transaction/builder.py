"""Build stable transaction records without merging independent statements."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import hashlib
import re

from bankocr.parser.models import CandidateStatus, TransactionCandidate
from bankocr.parser.normalization import normalize_amount, normalize_date


@dataclass(frozen=True, slots=True)
class TransactionRecord:
    transaction_id: str
    statement_stream_id: str
    candidate: TransactionCandidate
    transaction_date: date | None
    amount: Decimal | None
    balance: Decimal | None


class TransactionBuilder:
    """Turn page rows into stable records while preserving stream boundaries.

    A stream is derived from an explicit statement/section id first, then the
    account and currency fields.  If neither is present, the parser/layout id
    is the conservative fallback; rows are never joined merely because their
    dates happen to match.
    """

    def build(
        self,
        candidates: tuple[TransactionCandidate, ...] | list[TransactionCandidate],
        *,
        stream_overrides: dict[tuple[int, int], str] | None = None,
    ) -> tuple[TransactionRecord, ...]:
        overrides = stream_overrides or {}
        records: list[TransactionRecord] = []
        ordered_candidates = sorted(
            (
                candidate
                for candidate in candidates
                if candidate.status is not CandidateStatus.DUPLICATE
            ),
            key=lambda item: (
                item.page_index,
                item.review_order if item.review_order is not None else item.row_index,
                item.row_index,
            ),
        )
        for candidate in ordered_candidates:
            logical_key = overrides.get(
                (candidate.page_index, candidate.row_index),
                self._logical_stream_key(candidate),
            )
            stream_id = self._stable_stream_id(logical_key)
            transaction_id = f"{stream_id}:{candidate.page_index:04d}:{candidate.row_index:04d}"
            records.append(
                TransactionRecord(
                    transaction_id=transaction_id,
                    statement_stream_id=stream_id,
                    candidate=candidate,
                    transaction_date=self._date(candidate),
                    amount=self._amount(candidate),
                    balance=self._balance(candidate),
                )
            )
        return tuple(records)

    def group_by_stream(
        self,
        candidates: tuple[TransactionCandidate, ...] | list[TransactionCandidate],
        *,
        stream_overrides: dict[tuple[int, int], str] | None = None,
    ) -> dict[str, tuple[TransactionRecord, ...]]:
        groups: dict[str, list[TransactionRecord]] = {}
        for record in self.build(candidates, stream_overrides=stream_overrides):
            groups.setdefault(record.statement_stream_id, []).append(record)
        return {key: tuple(value) for key, value in groups.items()}

    @staticmethod
    def _logical_stream_key(candidate: TransactionCandidate) -> str:
        explicit = _field_text(candidate, ("statement_stream_id", "stream_id", "section_id"))
        account = _field_text(candidate, ("account_number", "account_id", "own_account", "account"))
        currency = _field_text(candidate, ("currency", "currency_code"))
        if explicit:
            return f"explicit:{_compact(explicit)}"
        if account or currency:
            return f"account:{_compact(account or '')}|currency:{_compact(currency or '')}"
        return f"layout:{candidate.parser_id}"

    @staticmethod
    def _stable_stream_id(logical_key: str) -> str:
        digest = hashlib.sha256(logical_key.encode("utf-8")).hexdigest()[:16]
        return f"stream-{digest}"

    @staticmethod
    def _date(candidate: TransactionCandidate) -> date | None:
        value = _field_text(candidate, ("transaction_date", "accounting_date", "date"))
        return normalize_date(value) if value else None

    @staticmethod
    def _amount(candidate: TransactionCandidate) -> Decimal | None:
        direct = _field_text(candidate, ("transaction_amount", "amount"))
        if direct:
            return normalize_amount(direct)
        income = normalize_amount(_field_text(candidate, ("income_amount", "income")) or "")
        expense = normalize_amount(_field_text(candidate, ("expense_amount", "expense")) or "")
        if income is None and expense is None:
            return None
        return (income or Decimal("0")) - (expense or Decimal("0"))

    @staticmethod
    def _balance(candidate: TransactionCandidate) -> Decimal | None:
        value = _field_text(candidate, ("balance", "online_balance", "closing_balance"))
        return normalize_amount(value) if value else None


def _field_text(candidate: TransactionCandidate, names: tuple[str, ...]) -> str | None:
    fields = dict(candidate.fields)
    for name in names:
        value = fields.get(name)
        if value is not None:
            return value.final_text or value.suggested_text or value.raw_text
    return None


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()
