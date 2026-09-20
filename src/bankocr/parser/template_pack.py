"""Declarative, hash-verified template packs for offline statement parsing."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from .templates import ColumnDefinition, TableTemplate


@dataclass(frozen=True, slots=True)
class TemplatePack:
    """A collection of JSON templates with a deterministic content fingerprint."""

    root: Path
    templates: tuple[TableTemplate, ...]
    files: tuple[tuple[str, str], ...]

    @classmethod
    def from_directory(
        cls,
        root: str | Path,
        *,
        manifest_path: str | Path | None = None,
    ) -> TemplatePack:
        directory = Path(root)
        if not directory.is_dir():
            raise FileNotFoundError(f"template pack directory does not exist: {directory}")
        paths = tuple(sorted(path for path in directory.glob("*.json") if path.name != "manifest.json"))
        if not paths:
            raise ValueError(f"template pack contains no JSON templates: {directory}")

        templates: list[TableTemplate] = []
        files: list[tuple[str, str]] = []
        seen_ids: set[str] = set()
        for path in paths:
            payload = _read_object(path)
            template = _template_from_dict(payload, path)
            if template.template_id in seen_ids:
                raise ValueError(f"duplicate template id: {template.template_id}")
            seen_ids.add(template.template_id)
            templates.append(template)
            files.append((path.name, _sha256(path)))

        pack = cls(directory, tuple(templates), tuple(files))
        if manifest_path is not None:
            pack._verify_manifest(Path(manifest_path))
        return pack

    @property
    def template_ids(self) -> tuple[str, ...]:
        return tuple(template.template_id for template in self.templates)

    @property
    def fingerprint(self) -> str:
        payload = "\n".join(f"{name}:{digest}" for name, digest in self.files)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def write_manifest(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(
                {
                    "format_version": 1,
                    "fingerprint": self.fingerprint,
                    "files": dict(self.files),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    def _verify_manifest(self, path: Path) -> None:
        payload = _read_object(path)
        if payload.get("format_version") != 1:
            raise ValueError("unsupported template manifest format")
        files = payload.get("files")
        if not isinstance(files, dict):
            raise ValueError("template manifest must contain a files object")
        expected = {str(name): str(digest) for name, digest in files.items()}
        if expected != dict(self.files):
            raise ValueError("template pack file checksum mismatch")
        fingerprint = payload.get("fingerprint")
        if not isinstance(fingerprint, str) or fingerprint.casefold() != self.fingerprint.casefold():
            raise ValueError("template pack fingerprint mismatch")


def template_to_dict(template: TableTemplate) -> dict[str, Any]:
    """Serialize a template without relying on dataclass implementation details."""

    return {
        "template_id": template.template_id,
        "version": template.version,
        "header_tokens": list(template.header_tokens),
        "columns": [
            {
                "name": column.name,
                "left_ratio": column.left_ratio,
                "right_ratio": column.right_ratio,
            }
            for column in template.columns
        ],
        "required_fields": list(template.required_fields),
        "row_strategy": template.row_strategy,
        "header_y_ratio": template.header_y_ratio,
    }


def template_from_dict(payload: dict[str, Any], source: str | Path = "<memory>") -> TableTemplate:
    return _template_from_dict(payload, Path(source))


def _template_from_dict(payload: dict[str, Any], source: Path) -> TableTemplate:
    try:
        columns_payload = payload["columns"]
        if not isinstance(columns_payload, list):
            raise TypeError("columns must be a list")
        columns = tuple(
            ColumnDefinition(
                name=str(item["name"]),
                left_ratio=float(item["left_ratio"]),
                right_ratio=float(item["right_ratio"]),
            )
            for item in columns_payload
        )
        header_tokens = tuple(str(token) for token in payload["header_tokens"])
        required_fields = tuple(str(name) for name in payload["required_fields"])
        return TableTemplate(
            template_id=str(payload["template_id"]),
            version=str(payload["version"]),
            header_tokens=header_tokens,
            columns=columns,
            required_fields=required_fields,
            row_strategy=str(payload.get("row_strategy", "grid")),
            header_y_ratio=float(payload.get("header_y_ratio", 0.25)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid template definition: {source}") from exc


def _read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid template JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"template JSON root must be an object: {path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
