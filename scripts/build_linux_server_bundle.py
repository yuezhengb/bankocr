"""Build a source-based Linux server bundle without user data."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
from typing import Iterable


def build_bundle(
    *,
    source_root: Path,
    model_dir: Path,
    template_dir: Path,
    font_file: Path,
    unit_file: Path,
    output_dir: Path,
) -> Path:
    """Copy only deployable runtime assets and write a SHA-256 manifest."""

    source_root = source_root.resolve()
    model_dir = model_dir.resolve()
    template_dir = template_dir.resolve()
    font_file = font_file.resolve()
    unit_file = unit_file.resolve()
    output_dir = output_dir.resolve()
    _validate_inputs(source_root, model_dir, template_dir, font_file, unit_file)
    for source in (source_root / "src" / "bankocr", model_dir, template_dir, font_file, unit_file):
        if _overlaps(output_dir, source):
            raise ValueError("output directory must not overlap an input asset")
    _prepare_output_directory(output_dir)

    shutil.copytree(
        source_root / "src" / "bankocr",
        output_dir / "src" / "bankocr",
        ignore=_ignore_python_cache,
    )
    for filename in ("pyproject.toml", "requirements-lock.txt", "requirements-linux-server.txt"):
        shutil.copy2(source_root / filename, output_dir / filename)
    shutil.copytree(model_dir, output_dir / "models", ignore=_ignore_python_cache)
    shutil.copytree(template_dir, output_dir / "templates" / "known", ignore=_ignore_python_cache)
    shutil.copy2(template_dir.parent / "manifest.json", output_dir / "templates" / "manifest.json")
    (output_dir / "fonts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(font_file, output_dir / "fonts" / "msyh.ttc")
    (output_dir / "deploy" / "systemd").mkdir(parents=True, exist_ok=True)
    shutil.copy2(unit_file, output_dir / "deploy" / "systemd" / "bankocr-server.service")

    model_manifest = json.loads((output_dir / "models" / "manifest.json").read_text(encoding="utf-8"))
    files = {
        path.relative_to(output_dir).as_posix(): _sha256(path)
        for path in sorted(_files(output_dir))
        if path.name != "bundle-manifest.json"
    }
    manifest = {
        "format_version": 1,
        "model_fingerprint": model_manifest.get("fingerprint"),
        "files": files,
    }
    (output_dir / "bundle-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_dir


def create_archive(bundle_dir: Path, archive_path: Path) -> Path:
    """Create a gzip tar archive whose root is the bundle contents."""

    bundle_dir = bundle_dir.resolve()
    archive_path = archive_path.resolve()
    if not bundle_dir.is_dir():
        raise FileNotFoundError(f"bundle directory does not exist: {bundle_dir}")
    if archive_path.parent == bundle_dir or archive_path.is_relative_to(bundle_dir):
        raise ValueError("archive must not be written inside the bundle directory")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "w:gz") as archive:
        for item in sorted(bundle_dir.iterdir()):
            archive.add(item, arcname=item.name)
    return archive_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--template-dir", type=Path, required=True)
    parser.add_argument("--font-file", type=Path, required=True)
    parser.add_argument("--unit-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args(argv)
    bundle_dir = build_bundle(
        source_root=args.source_root,
        model_dir=args.model_dir,
        template_dir=args.template_dir,
        font_file=args.font_file,
        unit_file=args.unit_file,
        output_dir=args.output_dir,
    )
    if args.archive is not None:
        create_archive(bundle_dir, args.archive)
    print(bundle_dir)
    return 0


def _validate_inputs(
    source_root: Path,
    model_dir: Path,
    template_dir: Path,
    font_file: Path,
    unit_file: Path,
) -> None:
    required_files = (
        source_root / "pyproject.toml",
        source_root / "requirements-lock.txt",
        source_root / "requirements-linux-server.txt",
        model_dir / "manifest.json",
        template_dir.parent / "manifest.json",
        font_file,
        unit_file,
    )
    required_dirs = (source_root / "src" / "bankocr", model_dir, template_dir)
    for path in required_files:
        if not path.is_file():
            raise FileNotFoundError(f"required bundle file does not exist: {path}")
    for path in required_dirs:
        if not path.is_dir():
            raise FileNotFoundError(f"required bundle directory does not exist: {path}")


def _prepare_output_directory(path: Path) -> None:
    if path.exists():
        if not path.is_dir():
            raise NotADirectoryError(f"output path is not a directory: {path}")
        if any(path.iterdir()):
            raise FileExistsError("output directory must be new or empty")
    else:
        path.mkdir(parents=True)


def _ignore_python_cache(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name == "__pycache__" or name.endswith(".pyc")}


def _files(root: Path) -> Iterable[Path]:
    return (path for path in root.rglob("*") if path.is_file())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _overlaps(output: Path, source: Path) -> bool:
    return output == source or output.is_relative_to(source) or source.is_relative_to(output)


if __name__ == "__main__":
    raise SystemExit(main())
