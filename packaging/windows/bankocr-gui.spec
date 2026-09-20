# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the offline main GUI.

The GUI resolves models, templates, and fonts next to ``bankocr-gui.exe``.
``build_offline_bundle.py`` assembles those adjacent runtime assets; do not
embed project-owned models, templates, or fonts in this executable.
"""

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
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "bankocr.gui.template_mapping",
]
datas = [
    *collect_data_files("rapidocr", include_py_files=False),
]

a = Analysis(
    [str(ROOT / "src" / "bankocr" / "gui_cli.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="bankocr-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
