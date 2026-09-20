import hashlib
import json
from pathlib import Path

from bankocr.ocr.model_pack import ModelPack
from bankocr.ocr.model_registry import ModelRegistry


def _pack(path: Path, marker: str) -> Path:
    path.mkdir()
    for name in ModelPack.REQUIRED_FILENAMES:
        (path / name).write_bytes(f"{marker}:{name}".encode())
    checksums = {
        name: hashlib.sha256((path / name).read_bytes()).hexdigest()
        for name in ModelPack.REQUIRED_FILENAMES
    }
    pack = ModelPack.from_directory(path, expected_sha256=checksums)
    (path / "manifest.json").write_text(
        json.dumps(
            {"format_version": 1, "fingerprint": pack.fingerprint, "files": checksums}
        ),
        encoding="utf-8",
    )
    return path


def test_model_registry_keeps_current_and_previous_for_explicit_rollback(tmp_path: Path) -> None:
    source_a = _pack(tmp_path / "a", "a")
    source_b = _pack(tmp_path / "b", "b")
    registry = ModelRegistry(tmp_path / "registry")

    first = registry.install(source_a, source_a / "manifest.json", activate=True)
    second = registry.install(source_b, source_b / "manifest.json", activate=True)

    assert registry.current().fingerprint == second.fingerprint
    assert registry.previous().fingerprint == first.fingerprint
    assert registry.rollback().fingerprint == first.fingerprint
