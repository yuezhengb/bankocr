# Known statement templates

JSON in this directory describes **page layout geometry** (header labels and column
ratios). It is not customer data.

Do not put real PDFs, account numbers, or sample transaction rows here.

To add a bank, follow [CONTRIBUTING.md](../CONTRIBUTING.md). After editing JSON,
regenerate `templates/manifest.json` so SHA-256 pins stay in sync.

Current layouts:

- `bohai_detail_v1` — grid-style detail statement
- `online_statement_v1` — position/anchor-date online statement
