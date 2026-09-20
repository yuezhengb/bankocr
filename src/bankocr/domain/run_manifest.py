"""Immutable provenance pins for a processing run."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re


_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True, slots=True)
class RunManifest:
    app_version: str
    project_schema_version: str
    ocr_engine: str
    ocr_model_id: str
    model_sha256: str
    execution_provider: str
    preprocess_profile: str
    parser_version: str
    template_version: str
    validation_rules_version: str
    exporter_version: str
    template_fingerprint: str = ""
    validation_rules_fingerprint: str = ""

    def __post_init__(self) -> None:
        fields = asdict(self)
        empty = [name for name, value in fields.items() if name not in {"template_fingerprint", "validation_rules_fingerprint"} and not value.strip()]
        if empty:
            raise ValueError(f"manifest fields must not be empty: {', '.join(empty)}")
        if not _SHA256.fullmatch(self.model_sha256):
            raise ValueError("model_sha256 must be a 64-character hexadecimal SHA-256")
        for name in ("template_fingerprint", "validation_rules_fingerprint"):
            value = getattr(self, name)
            if value and not _SHA256.fullmatch(value):
                raise ValueError(f"{name} must be a 64-character hexadecimal SHA-256 when supplied")

    def to_dict(self) -> dict[str, str]:
        return {
            name: value
            for name, value in asdict(self).items()
            if value or name not in {"template_fingerprint", "validation_rules_fingerprint"}
        }
