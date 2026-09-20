import hashlib
import json
from pathlib import Path
import shutil

import pytest

from bankocr.ocr.model_pack import ModelPack
from scripts import verify_offline_release


def test_verify_offline_release_checks_release_file_hashes(tmp_path: Path, monkeypatch) -> None:
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    for filename in ModelPack.REQUIRED_FILENAMES:
        (model_dir / filename).write_bytes(filename.encode("utf-8"))
    pack = ModelPack.from_directory(model_dir)
    manifest = model_dir / "manifest.json"
    manifest.write_text(
        json.dumps({"format_version": 1, "fingerprint": pack.fingerprint, "files": pack.checksums()}),
        encoding="utf-8",
    )
    release_root = tmp_path / "release"
    release_root.mkdir()
    release_models = release_root / "models"
    release_models.mkdir()
    for filename in ModelPack.REQUIRED_FILENAMES:
        shutil.copy2(model_dir / filename, release_models / filename)
    shutil.copy2(manifest, release_models / "manifest.json")
    wheel = release_root / "bankocr.whl"
    wheel.write_bytes(b"wheel")
    requirements = release_root / "requirements-lock.txt"
    requirements.write_text("bankocr==0.1.0\n", encoding="utf-8")
    executable = release_root / "bankocr-process.exe"
    executable.write_bytes(b"exe")
    files = {
        "bankocr.whl": hashlib.sha256(b"wheel").hexdigest(),
        "requirements-lock.txt": hashlib.sha256(requirements.read_bytes()).hexdigest(),
        "bankocr-process.exe": hashlib.sha256(b"exe").hexdigest(),
        "models/manifest.json": hashlib.sha256(
            (release_models / "manifest.json").read_bytes()
        ).hexdigest(),
    }
    files.update(
        {
            f"models/{filename}": hashlib.sha256(
                (release_models / filename).read_bytes()
            ).hexdigest()
            for filename in ModelPack.REQUIRED_FILENAMES
        }
    )
    release = release_root / "release.json"
    release.write_text(
        json.dumps(
            {
                "format_version": 1,
                "model_fingerprint": pack.fingerprint,
                "wheel": "bankocr.whl",
                "offline_assets_verified": True,
                "files": files,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "verify_offline_release.py",
            "--model-dir",
            str(model_dir),
            "--manifest",
            str(manifest),
            "--release-dir",
            str(release_root),
        ],
    )

    assert verify_offline_release.main() == 0


def test_verify_offline_release_rejects_incomplete_release_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    for filename in ModelPack.REQUIRED_FILENAMES:
        (model_dir / filename).write_bytes(filename.encode("utf-8"))
    pack = ModelPack.from_directory(model_dir)
    manifest = model_dir / "manifest.json"
    manifest.write_text(
        json.dumps({"format_version": 1, "fingerprint": pack.fingerprint, "files": pack.checksums()}),
        encoding="utf-8",
    )
    release_root = tmp_path / "release"
    release_root.mkdir()
    (release_root / "release.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "model_fingerprint": pack.fingerprint,
                "wheel": "bankocr.whl",
                "offline_assets_verified": True,
                "files": {"../outside.txt": hashlib.sha256(b"outside").hexdigest()},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "verify_offline_release.py",
            "--model-dir",
            str(model_dir),
            "--manifest",
            str(manifest),
            "--release-dir",
            str(release_root),
        ],
    )

    with pytest.raises(ValueError, match="required release asset"):
        verify_offline_release.main()


def test_verify_offline_release_rejects_zero_config_gui_without_adjacent_assets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    for filename in ModelPack.REQUIRED_FILENAMES:
        (model_dir / filename).write_bytes(filename.encode("utf-8"))
    pack = ModelPack.from_directory(model_dir)
    manifest = model_dir / "manifest.json"
    manifest.write_text(
        json.dumps({"format_version": 1, "fingerprint": pack.fingerprint, "files": pack.checksums()}),
        encoding="utf-8",
    )
    release_root = tmp_path / "release"
    release_root.mkdir()
    release_models = release_root / "models"
    release_models.mkdir()
    for filename in ModelPack.REQUIRED_FILENAMES:
        shutil.copy2(model_dir / filename, release_models / filename)
    shutil.copy2(manifest, release_models / "manifest.json")
    wheel = release_root / "bankocr.whl"
    wheel.write_bytes(b"wheel")
    requirements = release_root / "requirements-lock.txt"
    requirements.write_text("bankocr==0.1.0\n", encoding="utf-8")
    files = {
        "bankocr.whl": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "requirements-lock.txt": hashlib.sha256(requirements.read_bytes()).hexdigest(),
        "models/manifest.json": hashlib.sha256(
            (release_models / "manifest.json").read_bytes()
        ).hexdigest(),
        **{
            f"models/{filename}": hashlib.sha256(
                (release_models / filename).read_bytes()
            ).hexdigest()
            for filename in ModelPack.REQUIRED_FILENAMES
        },
    }
    (release_root / "release.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "model_fingerprint": pack.fingerprint,
                "wheel": "bankocr.whl",
                "offline_assets_verified": True,
                "zero_config_gui": True,
                "cjk_font_included": True,
                "files": files,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "verify_offline_release.py",
            "--model-dir",
            str(model_dir),
            "--manifest",
            str(manifest),
            "--release-dir",
            str(release_root),
        ],
    )

    with pytest.raises(ValueError, match="zero-config GUI release"):
        verify_offline_release.main()
