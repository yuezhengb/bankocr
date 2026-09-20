# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the offline CLI; OCR models stay in the adjacent model pack."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


ROOT = Path(SPECPATH).resolve().parents[1]

hiddenimports = [
    "onnxruntime",
    "openpyxl",
    *collect_submodules(
        "rapidocr",
        filter=lambda name: not any(
            f"rapidocr.inference_engine.{backend}" in name
            for backend in ("mnn", "openvino", "paddle", "pytorch", "tensorrt")
        ),
    ),
]
datas = [
    *collect_data_files("rapidocr", include_py_files=False),
    (str(ROOT / "templates"), "templates"),
]

a = Analysis(
    [str(ROOT / "src" / "bankocr" / "cli.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="bankocr-process",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
