"""Run a field-level V1 benchmark without writing OCR text to the report."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import json
from pathlib import Path

from bankocr.benchmark.golden import load_golden_sample
from bankocr.benchmark.v1 import V1BenchmarkRunner, V1Thresholds
from bankocr.ocr.model_pack import ModelPack
from bankocr.ocr.rapidocr_backend import RapidOCRBackend
from bankocr.pipeline.processor import DocumentProcessor


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=Path, nargs="+", required=True)
    parser.add_argument("--truth", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--model-manifest", type=Path)
    args = parser.parse_args()
    if len(args.pdf) != len(args.truth):
        parser.error("each PDF requires one Golden Sample JSON")
    if bool(args.model_dir) != bool(args.model_manifest):
        parser.error("--model-dir and --model-manifest must be provided together")
    backend = RapidOCRBackend(
        model_pack=(
            ModelPack.from_manifest(args.model_dir, args.model_manifest)
            if args.model_dir and args.model_manifest
            else None
        )
    )
    runner = V1BenchmarkRunner(DocumentProcessor(backend=backend))
    thresholds = V1Thresholds()
    metrics = []
    for source, truth_path in zip(args.pdf, args.truth):
        golden = load_golden_sample(truth_path)
        metrics.append(
            runner.run(source, golden.truths, dpi=args.dpi, thresholds=thresholds).to_dict()
        )
    payload = {
        "threshold_profile": "known-layout-v1",
        "thresholds": asdict(thresholds),
        "files": metrics,
        "gate_passed": all(item["gate_passed"] for item in metrics),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=tuple(metrics[0]) if metrics else ("source_file",))
            writer.writeheader()
            writer.writerows(metrics)
    print(args.output)
    return 0 if payload["gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
