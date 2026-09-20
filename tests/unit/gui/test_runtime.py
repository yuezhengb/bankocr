from pathlib import Path
import os

import pytest

from bankocr.gui import runtime


def test_resolve_gui_paths_uses_documents_bankocr_and_adjacent_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "windows_documents_dir", lambda: tmp_path / "Documents")
    root = tmp_path / "package"
    (root / "models").mkdir(parents=True)
    (root / "models" / "manifest.json").write_text("{}", encoding="utf-8")
    (root / "templates" / "known").mkdir(parents=True)

    paths = runtime.resolve_gui_paths(resource_root=root)

    assert paths.output_root == tmp_path / "Documents" / "BankOCR" / "\u8f93\u51fa"
    assert paths.project_db == tmp_path / "Documents" / "BankOCR" / "\u9879\u76ee" / "project.sqlite3"
    assert paths.model_dir == root / "models"
    assert paths.template_dir == root / "templates" / "known"


def test_missing_runtime_resources_reports_each_missing_asset(tmp_path):
    paths = runtime.resolve_gui_paths(resource_root=tmp_path, data_root=tmp_path / "data")

    missing = runtime.missing_runtime_resources(paths)

    assert "models" in missing
    assert "model manifest" in missing
    assert "known templates" in missing


def test_resolve_gui_paths_prefers_bundled_font(tmp_path):
    bundled_font = tmp_path / "fonts" / "msyh.ttc"
    bundled_font.parent.mkdir()
    bundled_font.write_bytes(b"font")

    paths = runtime.resolve_gui_paths(resource_root=tmp_path)

    assert paths.font_file == bundled_font


def test_resolve_gui_paths_rejects_explicit_missing_font(tmp_path):
    missing_font = tmp_path / "missing.ttc"

    with pytest.raises(FileNotFoundError, match="font"):
        runtime.resolve_gui_paths(resource_root=tmp_path, font_file=missing_font)

def test_missing_runtime_resources_requires_template_manifest(tmp_path):
    root = tmp_path / "package"
    (root / "models").mkdir(parents=True)
    (root / "models" / "manifest.json").write_text("{}", encoding="utf-8")
    (root / "templates" / "known").mkdir(parents=True)

    paths = runtime.resolve_gui_paths(resource_root=root, data_root=tmp_path / "data")

    assert "template manifest" in runtime.missing_runtime_resources(paths)


def test_resolve_gui_paths_honors_output_directory_override(tmp_path):
    output_dir = tmp_path / "diagnostic-output"

    paths = runtime.resolve_gui_paths(
        resource_root=tmp_path / "package",
        data_root=tmp_path / "data",
        output_dir=output_dir,
    )

    assert paths.output_root == output_dir.resolve()


@pytest.mark.skipif(os.name != "nt", reason="Path resolves to WindowsPath when os.name is patched to nt")
def test_resolve_gui_paths_does_not_use_system_font_when_bundled_font_is_missing(tmp_path, monkeypatch):
    windows_root = tmp_path / "Windows"
    system_font = windows_root / "Fonts" / "msyh.ttc"
    system_font.parent.mkdir(parents=True)
    system_font.write_bytes(b"system font")
    monkeypatch.setenv("WINDIR", str(windows_root))
    monkeypatch.setattr(runtime.os, "name", "nt")

    paths = runtime.resolve_gui_paths(resource_root=tmp_path / "package")

    assert paths.font_file is None
