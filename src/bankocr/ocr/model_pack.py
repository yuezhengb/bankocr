"""Explicit local RapidOCR model pack validation for offline execution."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping


_SHA256 = re.compile(r"[0-9a-f]{64}", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ModelPack:
    root: Path
    files: tuple[tuple[str, str], ...]

    REQUIRED_FILENAMES = (
        "PP-OCRv6_det_small.onnx",
        "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        "PP-OCRv6_rec_small.onnx",
    )

    @classmethod
    def from_directory(
        cls,
        root: str | Path,
        *,
        expected_sha256: Mapping[str, str] | None = None,
    ) -> ModelPack:
        path = Path(root)
        if not path.is_dir():
            raise FileNotFoundError(f"model pack directory does not exist: {path}")
        file_hashes: list[tuple[str, str]] = []
        for filename in cls.REQUIRED_FILENAMES:
            model_path = path / filename
            if not model_path.is_file():
                raise FileNotFoundError(f"required OCR model is missing: {model_path}")
            digest = _sha256(model_path)
            expected = (expected_sha256 or {}).get(filename)
            if expected is not None and digest.casefold() != expected.casefold():
                raise ValueError(f"OCR model checksum mismatch: {filename}")
            file_hashes.append((filename, digest))
        return cls(path, tuple(file_hashes))

    @classmethod
    def from_manifest(cls, root: str | Path, manifest_path: str | Path) -> ModelPack:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("model manifest must be an object")
        if manifest.get("format_version") != 1:
            raise ValueError("unsupported model manifest format")
        checksums = manifest.get("files")
        if not isinstance(checksums, dict):
            raise ValueError("model manifest must contain a files object")
        expected_checksums: dict[str, str] = {}
        for filename in cls.REQUIRED_FILENAMES:
            checksum = checksums.get(filename)
            if not isinstance(checksum, str) or not _SHA256.fullmatch(checksum):
                raise ValueError(
                    "model manifest has no valid checksum for required OCR model: "
                    f"{filename}"
                )
            expected_checksums[filename] = checksum
        pack = cls.from_directory(root, expected_sha256=expected_checksums)
        fingerprint = manifest.get("fingerprint")
        if not isinstance(fingerprint, str) or not _SHA256.fullmatch(fingerprint):
            raise ValueError("model manifest must contain a valid fingerprint")
        if fingerprint.casefold() != pack.fingerprint.casefold():
            raise ValueError("model manifest fingerprint mismatch")
        return pack

    @property
    def fingerprint(self) -> str:
        payload = "\n".join(f"{name}:{digest}" for name, digest in self.files).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def rapidocr_params(self) -> dict[str, str]:
        return {
            "Global.model_root_dir": str(self.root),
            "Global.log_level": "error",
        }

    def checksums(self) -> dict[str, str]:
        return dict(self.files)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
