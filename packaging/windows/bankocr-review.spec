# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the optional offline review executable."""

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parents[1]

# The GUI imports Qt lazily so the review module remains usable without the
# optional dependency.  Keep the frozen application focused on the modules it
# actually imports instead of collecting every PySide6 plugin and submodule.
hiddenimports = [
    "openpyxl",
    "bankocr.gui.template_mapping",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
]
datas = []

a = Analysis(
    [str(ROOT / "src" / "bankocr" / "review_cli.py")],
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
    name="bankocr-review",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
