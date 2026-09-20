"""Create a SHA-256 manifest for a local RapidOCR model pack."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bankocr.ocr.model_pack import ModelPack


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-id", default="PP-OCRv6-small")
    parser.add_argument("--provider", default="CPUExecutionProvider")
    parser.add_argument("--app-min-version", default="0.1.0")
    parser.add_argument("--app-max-version", default="0.x")
    args = parser.parse_args()
    pack = ModelPack.from_directory(args.model_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "format_version": 1,
                "model_id": args.model_id,
                "execution_provider": args.provider,
                "compatible_app_versions": [args.app_min_version, args.app_max_version],
                "fingerprint": pack.fingerprint,
                "files": pack.checksums(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
