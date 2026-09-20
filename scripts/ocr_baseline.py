from __future__ import annotations

import argparse
import json
from pathlib import Path

from bankocr.benchmark.baseline import OCRBaselineRunner
from bankocr.ocr.model_pack import ModelPack
from bankocr.ocr.rapidocr_backend import RapidOCRBackend


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a local OCR baseline without storing OCR text")
    parser.add_argument("pdf", nargs="+", type=Path, help="input PDF files")
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--model-manifest", type=Path)
    args = parser.parse_args()
    if bool(args.model_dir) != bool(args.model_manifest):
        parser.error("--model-dir and --model-manifest must be provided together")

    model_pack = (
        ModelPack.from_manifest(args.model_dir, args.model_manifest)
        if args.model_dir and args.model_manifest
        else None
    )
    runner = OCRBaselineRunner(backend=RapidOCRBackend(model_pack=model_pack))
    reports = [runner.run(path, dpi=args.dpi).to_dict() for path in args.pdf]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "engine": runner.backend.engine_id,
                "model_fingerprint": runner.backend.model_pack.fingerprint,
                "dpi": args.dpi,
                "files": reports,
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
