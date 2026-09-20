"""Runtime paths used by the zero-configuration GUI entry point."""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class GuiRuntimePaths:
    resource_root: Path
    data_root: Path
    output_root: Path
    project_db: Path
    log_root: Path
    model_dir: Path
    model_manifest: Path
    template_dir: Path
    font_file: Path | None


def resolve_gui_paths(
    *,
    resource_root: str | Path | None = None,
    data_root: str | Path | None = None,
    project_db: str | Path | None = None,
    model_dir: str | Path | None = None,
    model_manifest: str | Path | None = None,
    template_dir: str | Path | None = None,
    output_dir: str | Path | None = None,
    font_file: str | Path | None = None,
) -> GuiRuntimePaths:
    """Resolve packaged resources and writable per-user GUI paths."""
    resources = _path(resource_root) if resource_root is not None else _default_resource_root()
    data = _path(data_root) if data_root is not None else windows_documents_dir() / "BankOCR"
    models = _path(model_dir) if model_dir is not None else resources / "models"
    manifest = (
        _path(model_manifest)
        if model_manifest is not None
        else models / "manifest.json"
    )
    templates = (
        _path(template_dir)
        if template_dir is not None
        else resources / "templates" / "known"
    )
    resolved_font = _resolve_font(resources, font_file)
    return GuiRuntimePaths(
        resource_root=resources,
        data_root=data,
        output_root=_path(output_dir) if output_dir is not None else data / "\u8f93\u51fa",
        project_db=(
            _path(project_db)
            if project_db is not None
            else data / "\u9879\u76ee" / "project.sqlite3"
        ),
        log_root=data / "\u65e5\u5fd7",
        model_dir=models,
        model_manifest=manifest,
        template_dir=templates,
        font_file=resolved_font,
    )


def missing_runtime_resources(paths: GuiRuntimePaths) -> tuple[str, ...]:
    """Return stable user-facing names for resources absent from a runtime bundle."""
    missing: list[str] = []
    if not paths.model_dir.is_dir():
        missing.append("models")
    if not paths.model_manifest.is_file():
        missing.append("model manifest")
    if not paths.template_dir.is_dir():
        missing.append("known templates")
    if not (paths.template_dir.parent / "manifest.json").is_file():
        missing.append("template manifest")
    return tuple(missing)


def windows_documents_dir() -> Path:
    """Return the user's Documents directory, using the Windows known folder when possible."""
    if os.name == "nt":
        try:
            return _windows_known_documents_dir()
        except (AttributeError, OSError, RuntimeError, ValueError):
            pass
    return Path.home() / "Documents"


def _default_resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def _path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def _resolve_font(resource_root: Path, explicit: str | Path | None) -> Path | None:
    if explicit is not None:
        path = _path(explicit)
        if not path.is_file():
            raise FileNotFoundError(f"font file does not exist: {path}")
        return path

    candidate = resource_root / "fonts" / "msyh.ttc"
    if candidate.is_file():
        return candidate.resolve()
    return None


class _WindowsGuid(ctypes.Structure):
    _fields_ = (
        ("data1", wintypes.DWORD),
        ("data2", wintypes.WORD),
        ("data3", wintypes.WORD),
        ("data4", wintypes.BYTE * 8),
    )


def _windows_known_documents_dir() -> Path:
    shell32 = ctypes.windll.shell32
    ole32 = ctypes.windll.ole32
    guid = _WindowsGuid(
        0xFDD39AD0,
        0x238F,
        0x46AF,
        (0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7),
    )
    path_ptr = ctypes.POINTER(wintypes.WCHAR)()
    shell32.SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(_WindowsGuid),
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.POINTER(wintypes.WCHAR)),
    ]
    shell32.SHGetKnownFolderPath.restype = wintypes.LONG
    result = shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path_ptr))
    if result != 0:
        raise OSError(result, "SHGetKnownFolderPath failed")
    try:
        return Path(ctypes.wstring_at(path_ptr))
    finally:
        ole32.CoTaskMemFree(path_ptr)
