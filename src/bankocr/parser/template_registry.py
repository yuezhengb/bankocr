"""Verified template-pack slots with explicit activation and rollback."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil

from .template_pack import TemplatePack


@dataclass(frozen=True, slots=True)
class TemplateSlot:
    name: str
    fingerprint: str
    root: Path

    @property
    def template_dir(self) -> Path:
        return self.root / "known"

    @property
    def manifest(self) -> Path:
        return self.root / "manifest.json"


class TemplateRegistry:
    """Retain current/previous template assets so old runs remain reproducible."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.versions = self.root / "versions"
        self.pointer = self.root / "slots.json"
        self.versions.mkdir(parents=True, exist_ok=True)

    def install(
        self,
        template_dir: str | Path,
        manifest: str | Path,
        *,
        activate: bool = False,
    ) -> TemplateSlot:
        pack = TemplatePack.from_directory(template_dir, manifest_path=manifest)
        destination = self.versions / pack.fingerprint
        if not destination.exists():
            known = destination / "known"
            known.mkdir(parents=True, exist_ok=False)
            for name, _digest in pack.files:
                shutil.copy2(Path(template_dir) / name, known / name)
            shutil.copy2(manifest, destination / "manifest.json")
        slot = TemplateSlot("current", pack.fingerprint, destination)
        if activate:
            return self.activate(pack.fingerprint)
        return slot

    def activate(self, fingerprint: str) -> TemplateSlot:
        slot = self._verified_slot("current", fingerprint)
        slots = self._read_slots()
        current = slots.get("current")
        if current and current.casefold() != fingerprint.casefold():
            slots["previous"] = current
        slots["current"] = fingerprint
        self._write_slots(slots)
        return slot

    def current(self) -> TemplateSlot:
        return self._slot("current")

    def previous(self) -> TemplateSlot:
        return self._slot("previous")

    def rollback(self) -> TemplateSlot:
        current = self.current()
        previous = self.previous()
        slots = self._read_slots()
        slots["current"], slots["previous"] = slots["previous"], slots["current"]
        self._write_slots(slots)
        return TemplateSlot("current", previous.fingerprint, previous.root)

    def _slot(self, name: str) -> TemplateSlot:
        fingerprint = self._read_slots().get(name)
        if not fingerprint:
            raise FileNotFoundError(f"template registry has no {name} slot")
        return self._verified_slot(name, fingerprint)

    def _verified_slot(self, name: str, fingerprint: str) -> TemplateSlot:
        root = self.versions / fingerprint
        pack = TemplatePack.from_directory(root / "known", manifest_path=root / "manifest.json")
        if pack.fingerprint.casefold() != fingerprint.casefold():
            raise ValueError("template registry fingerprint mismatch")
        return TemplateSlot(name, pack.fingerprint, root)

    def _read_slots(self) -> dict[str, str]:
        if not self.pointer.exists():
            return {}
        payload = json.loads(self.pointer.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("template registry slots must be an object")
        return {
            str(key): str(value)
            for key, value in payload.items()
            if key in {"current", "previous"}
        }

    def _write_slots(self, slots: dict[str, str]) -> None:
        temporary = self.pointer.with_suffix(".tmp")
        temporary.write_text(json.dumps(slots, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(self.pointer)
