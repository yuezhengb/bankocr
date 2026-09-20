"""Assemble a wheel, locked dependencies, and verified OCR models for offline handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

from bankocr.ocr.model_pack import ModelPack


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--template-executable", type=Path)
    parser.add_argument("--review-executable", type=Path)
    parser.add_argument("--gui-executable", type=Path)
    parser.add_argument(
        "--template-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "templates" / "known",
    )
    parser.add_argument("--template-manifest", type=Path)
    parser.add_argument("--font-file", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    pack = ModelPack.from_manifest(args.model_dir, args.manifest)
    if not args.wheel.is_file() or not args.requirements.is_file():
        raise FileNotFoundError("wheel or locked requirements file is missing")
    if args.gui_executable is not None and args.font_file is None:
        raise ValueError("zero-config GUI bundle requires --font-file")
    for source in (
        args.wheel,
        args.requirements,
        args.model_dir,
        args.manifest,
        args.executable,
        args.template_executable,
        args.review_executable,
        args.gui_executable,
        args.template_dir,
        args.template_manifest,
        args.font_file,
    ):
        if source is not None and _overlaps(args.output_dir, source):
            raise ValueError("output directory must not contain or be contained by an input asset")
    _prepare_output_directory(args.output_dir)
    models = args.output_dir / "models"
    models.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    copied.append(_copy(args.wheel, args.output_dir / args.wheel.name))
    copied.append(_copy(args.requirements, args.output_dir / "requirements-lock.txt"))
    shutil.copy2(args.manifest, models / "manifest.json")
    copied.append(models / "manifest.json")
    for filename in ModelPack.REQUIRED_FILENAMES:
        copied.append(_copy(args.model_dir / filename, models / filename))
    templates = args.output_dir / "templates" / "known"
    templates.mkdir(parents=True, exist_ok=True)
    template_paths = tuple(sorted(args.template_dir.glob("*.json")))
    if not template_paths:
        raise FileNotFoundError(f"template directory contains no JSON files: {args.template_dir}")
    for template in template_paths:
        copied.append(_copy(template, templates / template.name))
    template_manifest = args.template_manifest or args.template_dir.parent / "manifest.json"
    if not template_manifest.is_file():
        raise FileNotFoundError(f"template manifest does not exist: {template_manifest}")
    copied.append(_copy(template_manifest, args.output_dir / "templates" / "manifest.json"))
    if args.font_file is not None:
        if not args.font_file.is_file():
            raise FileNotFoundError(f"CJK font does not exist: {args.font_file}")
        copied.append(_copy(args.font_file, args.output_dir / "fonts" / "msyh.ttc"))
    metadata = {
        "format_version": 1,
        "requirements_file": args.requirements.name,
        "third_party_license_notice": "THIRD_PARTY_NOTICES.md",
        "sbom_file": "sbom.cdx.json",
        "offline_assets_verified": True,
        "cjk_font_included": args.font_file is not None,
        "templates_included": True,
        "zero_config_gui": args.gui_executable is not None,
    }
    copied.append(_write_metadata(args.output_dir / "release-metadata.json", metadata))
    copied.append(_write_notices(args.output_dir / "THIRD_PARTY_NOTICES.md", args.requirements))
    if args.executable is not None:
        if not args.executable.is_file():
            raise FileNotFoundError(f"executable does not exist: {args.executable}")
        copied.append(_copy(args.executable, args.output_dir / args.executable.name))
    if args.template_executable is not None:
        if not args.template_executable.is_file():
            raise FileNotFoundError(f"template executable does not exist: {args.template_executable}")
        copied.append(_copy(args.template_executable, args.output_dir / args.template_executable.name))
    if args.review_executable is not None:
        if not args.review_executable.is_file():
            raise FileNotFoundError(f"review executable does not exist: {args.review_executable}")
        copied.append(_copy(args.review_executable, args.output_dir / args.review_executable.name))
    if args.gui_executable is not None:
        if not args.gui_executable.is_file():
            raise FileNotFoundError(f"GUI executable does not exist: {args.gui_executable}")
        copied.append(_copy(args.gui_executable, args.output_dir / "bankocr-gui.exe"))
    copied.append(
        _write_sbom(
            args.output_dir / "sbom.cdx.json",
            args.requirements,
            args.output_dir,
            copied,
        )
    )
    files = {
        str(path.relative_to(args.output_dir)).replace("\\", "/"): _sha256(path)
        for path in copied
    }
    (args.output_dir / "release.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "wheel": args.wheel.name,
                "model_fingerprint": pack.fingerprint,
                "offline_assets_verified": True,
                "templates_included": True,
                "sbom_included": True,
                "cjk_font_included": args.font_file is not None,
                "zero_config_gui": args.gui_executable is not None,
                "files": files,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(args.output_dir)
    return 0


def _copy(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def _prepare_output_directory(path: Path) -> None:
    if path.exists():
        if not path.is_dir():
            raise NotADirectoryError(f"output path is not a directory: {path}")
        if any(path.iterdir()):
            raise FileExistsError("output directory must be new or empty")
        return
    path.mkdir(parents=True)


def _write_metadata(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _write_notices(path: Path, requirements: Path) -> Path:
    lines = [
        "BankOCR third-party notices",
        "",
        "This release uses the packages pinned in requirements-lock.txt.",
        "The build owner must verify each package's license before redistribution.",
        "",
        *requirements.read_text(encoding="utf-8").splitlines(),
        "",
        "The optional CJK font is not included unless explicitly supplied by the release owner.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_sbom(
    path: Path,
    requirements: Path,
    root: Path,
    copied: list[Path],
) -> Path:
    pattern = re.compile(r"^([A-Za-z0-9_.-]+)==([0-9][A-Za-z0-9_.+-]*)")
    components = []
    for line in requirements.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line.strip())
        if match:
            components.append(
                {"type": "library", "name": match.group(1), "version": match.group(2)}
            )
    assets = {
        str(asset.relative_to(root)).replace("\\", "/"): _sha256(asset)
        for asset in copied
    }
    payload = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {"component": {"type": "application", "name": "BankOCR", "version": "0.1.0"}},
        "components": components,
        "properties": [
            {"name": "bankocr:asset-sha256", "value": json.dumps(assets, sort_keys=True)}
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _overlaps(output: Path, source: Path) -> bool:
    output_resolved = output.resolve()
    source_resolved = source.resolve()
    if source_resolved.is_dir():
        return output_resolved == source_resolved or output_resolved.is_relative_to(source_resolved)
    return source_resolved.parent == output_resolved or source_resolved.is_relative_to(output_resolved)


if __name__ == "__main__":
    raise SystemExit(main())
