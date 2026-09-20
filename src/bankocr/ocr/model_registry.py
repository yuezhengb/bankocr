"""Verified model-pack slots with explicit current/previous rollback."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil

from .model_pack import ModelPack


@dataclass(frozen=True, slots=True)
class ModelSlot:
    name: str
    fingerprint: str
    root: Path


class ModelRegistry:
    """Keep old run assets available while switching model versions explicitly."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.versions = self.root / "versions"
        self.pointer = self.root / "slots.json"
        self.versions.mkdir(parents=True, exist_ok=True)

    def install(self, model_dir: str | Path, manifest: str | Path, *, activate: bool = False) -> ModelSlot:
        pack = ModelPack.from_manifest(model_dir, manifest)
        destination = self.versions / pack.fingerprint
        if not destination.exists():
            destination.mkdir(parents=True, exist_ok=False)
            for name in ModelPack.REQUIRED_FILENAMES:
                shutil.copy2(Path(model_dir) / name, destination / name)
            shutil.copy2(manifest, destination / "manifest.json")
        slot = ModelSlot("current", pack.fingerprint, destination)
        if activate:
            self.activate(pack.fingerprint)
        return slot

    def activate(self, fingerprint: str) -> ModelSlot:
        destination = self.versions / fingerprint
        manifest = destination / "manifest.json"
        pack = ModelPack.from_manifest(destination, manifest)
        if pack.fingerprint.casefold() != fingerprint.casefold():
            raise ValueError("model registry fingerprint mismatch")
        slots = self._read_slots()
        current = slots.get("current")
        if current and current.casefold() != fingerprint.casefold():
            slots["previous"] = current
        slots["current"] = fingerprint
        self._write_slots(slots)
        return ModelSlot("current", pack.fingerprint, destination)

    def current(self) -> ModelSlot:
        return self._slot("current")

    def previous(self) -> ModelSlot:
        return self._slot("previous")

    def rollback(self) -> ModelSlot:
        current = self.current()
        previous = self.previous()
        slots = self._read_slots()
        slots["current"], slots["previous"] = slots["previous"], slots["current"]
        self._write_slots(slots)
        return ModelSlot("current", previous.fingerprint, previous.root)

    def _slot(self, name: str) -> ModelSlot:
        fingerprint = self._read_slots().get(name)
        if not fingerprint:
            raise FileNotFoundError(f"model registry has no {name} slot")
        root = self.versions / fingerprint
        pack = ModelPack.from_manifest(root, root / "manifest.json")
        return ModelSlot(name, pack.fingerprint, root)

    def _read_slots(self) -> dict[str, str]:
        if not self.pointer.exists():
            return {}
        payload = json.loads(self.pointer.read_text(encoding="utf-8"))
        return {str(key): str(value) for key, value in payload.items() if key in {"current", "previous"}}

    def _write_slots(self, slots: dict[str, str]) -> None:
        temporary = self.pointer.with_suffix(".tmp")
        temporary.write_text(json.dumps(slots, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(self.pointer)
