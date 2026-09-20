"""Verify that an offline release has every required OCR model and checksum."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from bankocr.ocr.model_pack import ModelPack
from bankocr.parser.template_pack import TemplatePack


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--release-dir",
        type=Path,
        help="optional assembled release directory containing release.json",
    )
    args = parser.parse_args()
    pack = ModelPack.from_manifest(args.model_dir, args.manifest)
    if args.release_dir is not None:
        _verify_release(args.release_dir, pack.fingerprint)
    print(f"model_fingerprint={pack.fingerprint}")
    print("offline_model_pack=ok")
    return 0


def _verify_release(root: Path, model_fingerprint: str) -> None:
    release_path = root / "release.json"
    payload = json.loads(release_path.read_text(encoding="utf-8"))
    if payload.get("model_fingerprint", "").casefold() != model_fingerprint.casefold():
        raise ValueError("release model fingerprint mismatch")
    if payload.get("offline_assets_verified") is not True:
        raise ValueError("release must be marked as offline_assets_verified")
    files = payload.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("release.json must contain a non-empty files object")
    wheel_name = payload.get("wheel")
    if not isinstance(wheel_name, str) or not wheel_name or "/" in wheel_name or "\\" in wheel_name:
        raise ValueError("release.json must name a wheel file")
    root_resolved = root.resolve()
    required = {
        wheel_name,
        "requirements-lock.txt",
        "models/manifest.json",
        *(f"models/{filename}" for filename in ModelPack.REQUIRED_FILENAMES),
    }
    if payload.get("zero_config_gui") is True:
        if payload.get("templates_included") is not True:
            raise ValueError("zero-config GUI release must include templates")
        if payload.get("cjk_font_included") is not True:
            raise ValueError("zero-config GUI release must include a CJK font")
        required.update({"bankocr-gui.exe", "fonts/msyh.ttc"})
    if payload.get("sbom_included") is True:
        required.add("sbom.cdx.json")
    if payload.get("templates_included") is True:
        template_root = root_resolved / "templates" / "known"
        template_manifest = root_resolved / "templates" / "manifest.json"
        if not template_root.is_dir() or not template_manifest.is_file():
            raise FileNotFoundError("offline release template pack is missing")
        template_pack = TemplatePack.from_directory(template_root, manifest_path=template_manifest)
        required.update(
            {
                "templates/manifest.json",
                *(f"templates/known/{name}" for name, _ in template_pack.files),
                "release-metadata.json",
                "THIRD_PARTY_NOTICES.md",
            }
        )
    missing = sorted(required - {str(relative) for relative in files})
    if missing:
        raise ValueError(f"required release asset is missing from release.json: {missing[0]}")
    for relative, expected in files.items():
        path = _resolve_asset(root_resolved, str(relative))
        if not path.is_file():
            raise FileNotFoundError(f"release asset is missing: {path}")
        actual = _sha256(path)
        if actual.casefold() != str(expected).casefold():
            raise ValueError(f"release asset checksum mismatch: {relative}")


def _resolve_asset(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute():
        raise ValueError(f"release asset path must be relative: {relative}")
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"release asset path escapes release directory: {relative}")
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
