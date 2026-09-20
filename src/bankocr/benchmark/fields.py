"""Field-level Golden Sample evaluation for regression gates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from bankocr.parser.models import TransactionCandidate


@dataclass(frozen=True, slots=True)
class GoldenTransactionTruth:
    page_index: int
    row_index: int
    fields: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class FieldBenchmarkReport:
    total_fields: int
    exact_matches: int
    missing_predictions: tuple[str, ...]
    mismatches: tuple[str, ...]
    extra_predictions: tuple[str, ...]

    @property
    def accuracy(self) -> float:
        return self.exact_matches / self.total_fields if self.total_fields else 0.0


class FieldBenchmarkEvaluator:
    def evaluate(
        self,
        predictions: tuple[TransactionCandidate, ...] | list[TransactionCandidate],
        truths: tuple[GoldenTransactionTruth, ...] | list[GoldenTransactionTruth],
    ) -> FieldBenchmarkReport:
        prediction_map: dict[tuple[int, int], TransactionCandidate] = {}
        for candidate in predictions:
            key = (candidate.page_index, candidate.row_index)
            if key in prediction_map:
                raise ValueError(f"duplicate prediction key: {key}")
            prediction_map[key] = candidate
        truth_map: dict[tuple[int, int], GoldenTransactionTruth] = {}
        for truth in truths:
            key = (truth.page_index, truth.row_index)
            if key in truth_map:
                raise ValueError(f"duplicate truth key: {key}")
            truth_map[key] = truth

        exact = 0
        total = 0
        missing: list[str] = []
        mismatches: list[str] = []
        for key, truth in truth_map.items():
            candidate = prediction_map.get(key)
            fields = dict(candidate.fields) if candidate else {}
            for name, expected in truth.fields.items():
                total += 1
                label = f"{key[0]}:{key[1]}:{name}"
                value = fields.get(name)
                actual = None if value is None else (value.final_text if value.final_text is not None else value.suggested_text)
                if actual is None:
                    missing.append(label)
                elif actual == expected:
                    exact += 1
                else:
                    mismatches.append(label)
        extra = [
            f"{key[0]}:{key[1]}"
            for key in prediction_map.keys() - truth_map.keys()
        ]
        return FieldBenchmarkReport(
            total_fields=total,
            exact_matches=exact,
            missing_predictions=tuple(sorted(missing)),
            mismatches=tuple(sorted(mismatches)),
            extra_predictions=tuple(sorted(extra)),
        )
