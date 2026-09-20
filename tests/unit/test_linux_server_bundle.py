from __future__ import annotations

import json
from pathlib import Path

from scripts.build_linux_server_bundle import build_bundle


def test_build_bundle_copies_runtime_assets_and_excludes_user_data(tmp_path: Path) -> None:
    source_root = tmp_path / "repo"
    (source_root / "src" / "bankocr").mkdir(parents=True)
    (source_root / "src" / "bankocr" / "server.py").write_text("print('server')", encoding="utf-8")
    (source_root / "pyproject.toml").write_text("[project]\nname='bankocr'\n", encoding="utf-8")
    (source_root / "requirements-lock.txt").write_text("numpy==2.5.1\n", encoding="utf-8")
    (source_root / "requirements-linux-server.txt").write_text(
        "opencv-python==5.0.0.93\n", encoding="utf-8"
    )
    (source_root / "work").mkdir()
    (source_root / "work" / "private.pdf").write_bytes(b"%PDF-private")
    (source_root / "work" / "private.sqlite3").write_bytes(b"sqlite-private")

    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "manifest.json").write_text('{"fingerprint":"model-1"}', encoding="utf-8")
    (model_dir / "det.onnx").write_bytes(b"model")
    template_dir = tmp_path / "templates" / "known"
    template_dir.mkdir(parents=True)
    (template_dir / "demo.json").write_text("{}", encoding="utf-8")
    (template_dir.parent / "manifest.json").write_text('{"fingerprint":"template-1"}', encoding="utf-8")
    font_file = tmp_path / "msyh.ttc"
    font_file.write_bytes(b"font")
    unit_file = tmp_path / "bankocr-server.service"
    unit_file.write_text("[Service]\n", encoding="utf-8")

    output_dir = tmp_path / "bundle"
    result = build_bundle(
        source_root=source_root,
        model_dir=model_dir,
        template_dir=template_dir,
        font_file=font_file,
        unit_file=unit_file,
        output_dir=output_dir,
    )

    assert result == output_dir
    assert (output_dir / "src" / "bankocr" / "server.py").is_file()
    assert (output_dir / "models" / "manifest.json").is_file()
    assert (output_dir / "templates" / "manifest.json").is_file()
    assert (output_dir / "deploy" / "systemd" / "bankocr-server.service").is_file()
    assert (output_dir / "fonts" / "msyh.ttc").is_file()
    assert not list(output_dir.rglob("*.pdf"))
    assert not list(output_dir.rglob("*.sqlite3"))
    manifest = json.loads((output_dir / "bundle-manifest.json").read_text(encoding="utf-8"))
    assert manifest["model_fingerprint"] == "model-1"
    assert "src/bankocr/server.py" in manifest["files"]
