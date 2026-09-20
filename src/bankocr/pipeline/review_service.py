"""Revalidate reviewed final values before updating a persisted run."""

from __future__ import annotations

from bankocr.gui.review_model import ReviewSession
from bankocr.parser.models import TransactionCandidate
from bankocr.storage.project_store import ProjectStore
from bankocr.validation.engine import TransactionValidator, ValidationReport


class ReviewService:
    def __init__(
        self,
        store: ProjectStore,
        validator: TransactionValidator | None = None,
    ) -> None:
        self.store = store
        self.validator = validator or TransactionValidator()

    def save(
        self,
        run_id: int,
        candidates: tuple[TransactionCandidate, ...] | list[TransactionCandidate],
    ) -> dict[int, ValidationReport]:
        candidate_values = tuple(candidates)
        reports = self.validator.validate_document(candidate_values)
        self.store.save_review(run_id, candidate_values, validation_reports=reports)
        return reports

    def save_session(
        self,
        run_id: int,
        session: ReviewSession,
        *,
        reviewer: str = "local-user",
    ) -> dict[int, ValidationReport]:
        """Persist a complete immutable review session, including structure edits."""

        candidate_values = tuple(session.candidates)
        reports = self.validator.validate_document(candidate_values)
        self.store.save_structure_review(
            run_id,
            candidate_values,
            operations=session.operations,
            validation_reports=reports,
            reviewer=reviewer,
        )
        return reports
