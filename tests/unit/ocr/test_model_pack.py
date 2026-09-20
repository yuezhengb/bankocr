import hashlib
import json
from pathlib import Path

import pytest

from bankocr.ocr.model_pack import ModelPack


def _write_models(tmp_path: Path) -> dict[str, str]:
    contents = {name: name.encode("utf-8") for name in ModelPack.REQUIRED_FILENAMES}
    for name, content in contents.items():
        (tmp_path / name).write_bytes(content)
    return {name: hashlib.sha256(content).hexdigest() for name, content in contents.items()}


def _write_manifest(tmp_path: Path, checksums: dict[str, str], **overrides: object) -> Path:
    pack = ModelPack.from_directory(tmp_path, expected_sha256=checksums)
    payload = {
        "format_version": 1,
        "fingerprint": pack.fingerprint,
        "files": checksums,
        **overrides,
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    return manifest


def test_model_pack_validates_required_files_and_exposes_reproducible_fingerprint(tmp_path: Path) -> None:
    checksums = _write_models(tmp_path)

    pack = ModelPack.from_directory(tmp_path, expected_sha256=checksums)

    assert pack.fingerprint
    assert pack.rapidocr_params()["Global.model_root_dir"] == str(tmp_path)


def test_model_pack_fails_before_rapidocr_can_attempt_a_network_download(tmp_path: Path) -> None:
    (tmp_path / ModelPack.REQUIRED_FILENAMES[0]).write_bytes(b"only one")

    with pytest.raises(FileNotFoundError):
        ModelPack.from_directory(tmp_path)


def test_model_pack_can_verify_a_saved_manifest(tmp_path: Path) -> None:
    checksums = _write_models(tmp_path)
    manifest = _write_manifest(tmp_path, checksums)

    pack = ModelPack.from_manifest(tmp_path, manifest)

    assert pack.checksums() == checksums


def test_model_pack_rejects_manifest_missing_a_required_checksum(tmp_path: Path) -> None:
    checksums = _write_models(tmp_path)
    manifest = _write_manifest(tmp_path, checksums)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["files"].pop(ModelPack.REQUIRED_FILENAMES[-1])
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="required OCR model"):
        ModelPack.from_manifest(tmp_path, manifest)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"format_version": 2}, "format"),
        ({"fingerprint": None}, "fingerprint"),
    ],
)
def test_model_pack_requires_a_supported_format_and_matching_fingerprint(
    tmp_path: Path,
    overrides: dict[str, object],
    message: str,
) -> None:
    checksums = _write_models(tmp_path)
    manifest = _write_manifest(tmp_path, checksums, **overrides)

    with pytest.raises(ValueError, match=message):
        ModelPack.from_manifest(tmp_path, manifest)


def test_model_pack_rejects_manifest_with_a_forged_fingerprint(tmp_path: Path) -> None:
    checksums = _write_models(tmp_path)
    manifest = _write_manifest(tmp_path, checksums, fingerprint="0" * 64)

    with pytest.raises(ValueError, match="fingerprint"):
        ModelPack.from_manifest(tmp_path, manifest)
