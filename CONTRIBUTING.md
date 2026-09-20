# Contributing to BankOCR

Thanks for helping. Please read [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) first.

BankOCR processes bank statements. **Never** attach, commit, or paste:

- real PDFs, scans, screenshots, or Excel exports
- account numbers, names, ID numbers, phone numbers, or transaction text
- passwords, tokens, `.env` files, htpasswd files, or private keys

Use synthetic PDFs or redacted geometry-only examples.

## Development setup

Python 3.12+:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[test]"
export PYTHONPATH=src
export QT_QPA_PLATFORM=offscreen   # GUI tests without a display
.venv/bin/python -m pytest --basetemp=.pytest-tmp -q
.venv/bin/python -m compileall -q src tests scripts
```

Windows developers can use `.venv\Scripts\python.exe` and `.\scripts\build_windows.ps1` as described in `packaging/windows/README.md`. GUI extras: `pip install -e ".[gui]"`.

## Best first contribution: a new bank template

Known layouts live in `templates/known/*.json`. They store **header tokens and page-relative column ratios**, not customer rows.

1. Open a statement locally (do not commit it).
2. Note the header labels left-to-right and the left/right edge of each column as a fraction of page width (`0.0`–`1.0`).
3. Add `templates/known/<bank_or_layout>_v1.json`. Keep `template_id` identical to the file stem.

```json
{
  "template_id": "example_bank_v1",
  "version": "1",
  "header_tokens": ["交易日期", "交易金额", "余额"],
  "columns": [
    {"name": "transaction_date", "left_ratio": 0.03, "right_ratio": 0.18},
    {"name": "transaction_amount", "left_ratio": 0.18, "right_ratio": 0.40},
    {"name": "balance", "left_ratio": 0.40, "right_ratio": 0.58}
  ],
  "required_fields": ["transaction_date", "transaction_amount", "balance"],
  "row_strategy": "grid",
  "header_y_ratio": 0.25
}
```

`row_strategy` is one of `grid`, `anchor_date`, or `positional`. See the existing `bohai_detail_v1` (grid) and `online_statement_v1` (anchor_date) files. Those IDs describe **layout families**, not a customer's account.

4. Rebuild the pack manifest (checksums must match the JSON files):

```bash
export PYTHONPATH=src
python - <<'PY'
from pathlib import Path
from bankocr.parser.template_pack import TemplatePack
root = Path("templates/known")
pack = TemplatePack.from_directory(root)
pack.write_manifest(root.parent / "manifest.json")
print(pack.template_ids)
print(pack.fingerprint)
PY
```

5. Add a focused unit test in `tests/unit/parser/` that asserts header tokens, required fields, and column order. Prefer synthetic `TextBlock` fixtures over real OCR dumps.
6. Run `pytest` and open a pull request. In the PR, say which bank/layout you matched and confirm no customer data is included.

A Temporary Template saved from the review GUI applies to **one run only** and must not be copied into `templates/known` until it is reviewed as a general layout.

## Other useful work

- Synthetic golden samples following `benchmark/README.md` (structure only, no source PDF)
- Parser tests for a weird date or amount format
- Docs translations that do not add deployment secrets
- Linux packaging or CI that keeps tests offline

## Pull requests

- One concern per PR when possible.
- Do not rewrite the pipeline unless the change needs it.
- Do not add network calls on the processing path.
- Fill in `.github/pull_request_template.md`.

## Reporting issues

Use the GitHub issue templates. For vulnerabilities, see [SECURITY.md](SECURITY.md) instead of filing a public issue with exploit detail or sample statements.
