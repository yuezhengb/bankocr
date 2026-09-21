# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Public GitHub presence: bilingual README badges, contribution callouts, and starter good-first issues.
- Related curated list: [awesome-offline-ocr](https://github.com/yuezhengb/awesome-offline-ocr).
- Synthetic before/after README illustration (`docs/images/demo.svg`) via [#7](https://github.com/yuezhengb/bankocr/pull/7) (thanks [@Voyagerroc-Lab](https://github.com/Voyagerroc-Lab)); closes [#4](https://github.com/yuezhengb/bankocr/issues/4).

### Planned
- More known bank layout templates from the community.
- Optional recorded screen demo (GIF/MP4) of a real local run on synthetic PDFs.

## [0.1.0-rc] - 2026-09-21

First public snapshot of BankOCR as an open-source release candidate.

### Added
- Offline bank-statement PDF pipeline: structured Excel, pdf-layout workbook, review workbook, searchable PDF, comparison PDF, export manifest, and summary JSON.
- CPU-first OCR path (RapidOCR / ONNX Runtime oriented) with local model manifests.
- Known-template parsers plus fail-closed generic handling and financial validation (`Decimal`).
- Resumable SQLite project runs; Windows GUI and optional Linux loopback web UI.
- Contribution scaffolding: MIT license, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, issue/PR templates.

### Notes
- A formal **v1.0** tag is not claimed yet; see release-gate docs in the repository.
- Engineering baseline numbers in the README are local results on limited samples, not a published multi-bank benchmark.
