import hashlib
import json
from pathlib import Path

import pytest

from bankocr.ocr.model_pack import ModelPack
from scripts import build_offline_bundle


def test_build_offline_bundle_records_all_copied_asset_hashes(tmp_path: Path, monkeypatch) -> None:
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
    wheel = tmp_path / "bankocr.whl"
    requirements = tmp_path / "requirements-lock.txt"
    executable = tmp_path / "bankocr-process.exe"
    template_executable = tmp_path / "bankocr-template.exe"
    wheel.write_bytes(b"wheel")
    requirements.write_text("bankocr==0.1.0\n", encoding="utf-8")
    executable.write_bytes(b"exe")
    template_executable.write_bytes(b"template-exe")
    output = tmp_path / "release"

    monkeypatch.setattr(
        "sys.argv",
        [
            "build_offline_bundle.py",
            "--wheel",
            str(wheel),
            "--requirements",
            str(requirements),
            "--model-dir",
            str(model_dir),
            "--manifest",
            str(manifest),
            "--executable",
            str(executable),
            "--template-executable",
            str(template_executable),
            "--output-dir",
            str(output),
        ],
    )

    assert build_offline_bundle.main() == 0

    release = json.loads((output / "release.json").read_text(encoding="utf-8"))
    assert release["model_fingerprint"] == pack.fingerprint
    assert release["files"]["bankocr-process.exe"] == hashlib.sha256(b"exe").hexdigest()
    assert release["files"]["bankocr-template.exe"] == hashlib.sha256(b"template-exe").hexdigest()
    assert release["sbom_included"] is True
    assert (output / "sbom.cdx.json").is_file()
    assert (output / "models" / "manifest.json").is_file()


def test_output_directory_must_be_new_or_empty(tmp_path: Path) -> None:
    output = tmp_path / "release"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError, match="new or empty"):
        build_offline_bundle._prepare_output_directory(output)

    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_build_offline_bundle_includes_zero_config_gui_assets(tmp_path: Path, monkeypatch) -> None:
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
    template_dir = tmp_path / "templates" / "known"
    template_dir.mkdir(parents=True)
    (template_dir / "known.json").write_text("{}", encoding="utf-8")
    template_manifest = template_dir.parent / "manifest.json"
    template_manifest.write_text("{}", encoding="utf-8")
    wheel = tmp_path / "bankocr.whl"
    requirements = tmp_path / "requirements-lock.txt"
    gui_executable = tmp_path / "custom-gui.exe"
    font_file = tmp_path / "licensed-font.ttc"
    wheel.write_bytes(b"wheel")
    requirements.write_text("bankocr==0.1.0\n", encoding="utf-8")
    gui_executable.write_bytes(b"gui")
    font_file.write_bytes(b"font")
    output = tmp_path / "release"

    monkeypatch.setattr(
        "sys.argv",
        [
            "build_offline_bundle.py",
            "--wheel",
            str(wheel),
            "--requirements",
            str(requirements),
            "--model-dir",
            str(model_dir),
            "--manifest",
            str(manifest),
            "--template-dir",
            str(template_dir),
            "--template-manifest",
            str(template_manifest),
            "--gui-executable",
            str(gui_executable),
            "--font-file",
            str(font_file),
            "--output-dir",
            str(output),
        ],
    )

    assert build_offline_bundle.main() == 0

    release = json.loads((output / "release.json").read_text(encoding="utf-8"))
    metadata = json.loads((output / "release-metadata.json").read_text(encoding="utf-8"))
    expected_assets = {
        "bankocr-gui.exe",
        "models/manifest.json",
        *(f"models/{filename}" for filename in ModelPack.REQUIRED_FILENAMES),
        "templates/manifest.json",
        "templates/known/known.json",
        "fonts/msyh.ttc",
    }
    assert expected_assets <= set(release["files"])
    assert release["zero_config_gui"] is True
    assert release["offline_assets_verified"] is True
    assert release["cjk_font_included"] is True
    assert metadata["cjk_font_included"] is True
    assert metadata["offline_assets_verified"] is True
