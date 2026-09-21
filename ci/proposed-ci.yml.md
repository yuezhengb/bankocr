# Proposed minimal `ci.yml` (smoke)

Full CI already exists at [`.github/workflows/tests.yml`](../.github/workflows/tests.yml)
(Windows + Linux pytest, compileall, packaging smoke; rapidocr supplies ONNX models).

This draft adds a **lighter named `ci.yml`** smoke job. Automation could not write
under `.github/workflows/` (GitHub App/token missing `workflow` scope — API returns 404).

**To install:** copy the YAML below to `.github/workflows/ci.yml` and push.

```yaml
name: ci

# Minimal smoke CI that stays green on a fresh clone without committed ONNX models.
# Full suite already lives in .github/workflows/tests.yml.

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Compile sources (no model / heavy deps required)
        run: python -m compileall -q src tests scripts

      - name: Install package with test extras
        run: |
          sudo apt-get update
          sudo apt-get install -y libgl1
          python -m pip install -e ".[test]"

      - name: Unit smoke (domain + validation; no ONNX inference)
        env:
          QT_QPA_PLATFORM: offscreen
        run: >
          python -m pytest --basetemp=.pytest-tmp -q
          tests/unit/domain
          tests/unit/validation
```
