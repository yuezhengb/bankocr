# Security policy

## Bank statements are sensitive

Do not open a public GitHub issue that includes a real PDF, screenshot, account
number, name, or transaction line. Reproduce bugs with synthetic documents.

## Reporting a vulnerability

Please use GitHub's **private vulnerability reporting** on this repository
(Security → Report a vulnerability) if it is enabled, or contact the repository
owner through GitHub. Allow time for a patch before any public write-up.

Include:

- affected version or commit
- what an attacker could do
- a minimal synthetic proof if one is needed

Do not attach customer data.

## Secrets and local files

The processing path is intended to stay offline. Please keep the following out
of git and out of issue trackers:

- `.env`, htpasswd files, TLS private keys, API tokens
- `models/*.onnx` if your redistribution license does not allow it (see `models/README.md`)
- `*.sqlite3` project databases and export workbooks from real jobs
