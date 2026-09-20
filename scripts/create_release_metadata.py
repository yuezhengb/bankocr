"""Generate reproducible SBOM and third-party notice metadata for a release."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    requirements = root / "requirements-lock.txt"
    components = _components(requirements)
    files = _file_hashes(root)
    payload = {
        "format": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {"tool": "bankocr-create-release-metadata", "python": sys.version.split()[0]},
        "components": components,
        "files": files,
        "files_sha256": hashlib.sha256(
            json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(args.output)
    return 0


def _components(requirements: Path) -> list[dict[str, str]]:
    if not requirements.is_file():
        return []
    result: list[dict[str, str]] = []
    pattern = re.compile(r"^([A-Za-z0-9_.-]+)==([0-9][A-Za-z0-9_.+-]*)")
    for line in requirements.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line.strip())
        if match:
            result.append({"type": "library", "name": match.group(1), "version": match.group(2)})
    return result


def _file_hashes(root: Path) -> dict[str, str]:
    ignored = {".git", ".venv", ".pytest_cache", ".pytest-tmp", "work", "build"}
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in ignored for part in path.relative_to(root).parts):
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        result[str(path.relative_to(root)).replace("\\", "/")] = digest
    return result


if __name__ == "__main__":
    raise SystemExit(main())
