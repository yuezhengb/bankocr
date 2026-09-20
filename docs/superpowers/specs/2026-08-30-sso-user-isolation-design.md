# Optional identity-provider SSO and per-user isolation

**Status:** unimplemented design notes for self-hosters who already have an identity provider (IdP). Not required for CLI or desktop GUI use.  
**Date:** 2026-08-30

This document used to describe a company-specific integration. Production hostnames, IPs, SSH ports, sibling-product paths, and operator inventory have been removed. The remaining text is a generic protocol so a future contributor can implement SSO without copying passwords into BankOCR.

## 1. Goals

1. Users should not need a second BankOCR password if they already authenticate at an IdP.
2. Each user sees, downloads, and deletes only their own PDFs and results.
3. IdP administrators can create, disable, and reset accounts, but that must not automatically grant them other users' statements.
4. Concurrent uploads share one low-resource FIFO OCR worker. The UI shows real queue state without other users' filenames.
5. Task records survive a BankOCR process restart.
6. Browser traffic uses HTTPS/TLS. Files are not sent to third-party OCR, object storage, or model APIs.
7. SSO secrets live in root-only environment files, never in git, logs, HTML, or job output.

## 2. Current BankOCR web baseline

- Service: `bankocr-server` (see `deploy/systemd/bankocr-server.service`)
- Default listen: `127.0.0.1:18081`
- Suggested public name in examples: `https://ocr.example.com`
- Suggested install root: `/opt/bankocr-server`
- Today's protection is whatever the reverse proxy provides (example: HTTP basic auth).
- Job index is in-memory; task directories remain on disk but disappear from the UI after restart.
- There is no per-user ownership check on list or download endpoints.
- Keep a single OCR worker unless the host has been sized for parallel jobs.

## 3. Principles

1. **Do not share passwords.** BankOCR never receives, stores, or checks IdP passwords.
2. **Do not broaden IdP cookies** to every subdomain just so OCR can read them.
3. **Random job ids are not authorization.** Every query and download must check the session and the owner.
4. **Admin role ≠ file access.** Account administration must not imply read access to other users' statements.
5. **Honest status.** If there is no page-level progress, show queued / processing / completed / failed — not a fake percentage.
6. **Low resource first.** One global FIFO worker by default.
7. **Secrets stay off git.** `BANKOCR_SSO_SECRET` is at least 32 random bytes in a root-only env file on each host that needs it.

## 4. Chosen approach: short-lived signed assertion

The IdP, after confirming the user is signed in and enabled, mints a 90-second, single-use HMAC-SHA256 assertion and auto-POSTs it to BankOCR. BankOCR verifies the assertion and creates its own session.

Rejected alternatives:

- Sharing the IdP session cookie across subdomains (larger cookie blast radius; BankOCR cannot safely read another host's session store).
- Duplicating usernames and passwords inside BankOCR (two logins, drift, extra secret surface).

```text
browser
  -> sign in at the IdP
  -> IdP mints a 90s one-time assertion
  -> HTTPS form POST to https://ocr.example.com/auth/callback
  -> BankOCR verifies HMAC, iss, aud, exp, jti
  -> local BankOCR session + per-user job directories
```

The two systems share only the signing protocol and the SSO secret. They do not share passwords, cookies, or database files.

## 5. Assertion format

Compact three-part Base64URL:

```text
base64url(header).base64url(payload).base64url(signature)
```

Header:

```json
{"alg":"HS256","typ":"BankOCR-SSO","v":1}
```

Payload:

| Field | Meaning |
|---|---|
| `iss` | IdP identifier, for example `identity-provider` |
| `aud` | `bankocr-web` |
| `sub` | Stable user id from the IdP |
| `username` | Login name for display and audit |
| `display_name` | Display name |
| `role` | `admin` or `operator` |
| `iat` | UTC Unix seconds |
| `exp` | `iat + 90` |
| `jti` | 32-byte CSPRNG value, Base64URL |

Signature:

```text
HMAC-SHA256(BANKOCR_SSO_SECRET, encoded_header + "." + encoded_payload)
```

POST the assertion in a hidden form field named `assertion`. Do not put it in a query string (history, proxy logs, Referer).

BankOCR must verify structure, algorithm, constant-time HMAC, `iss`/`aud`, clocks (`iat` skew ≤ 30s, lifetime ≤ 90s), field types, and unused `jti` (persist `jti` with a unique index). On success, bind the local user as `idp:<sub>`.

Local session cookie: `bankocr_session` with `Secure; HttpOnly; SameSite=Lax; Path=/`. Store only the SHA-256 of a 32-byte random value. Absolute lifetime 8 hours, no overnight sliding renewal. Logging out of OCR does not log the user out of the IdP. Disabling an IdP account blocks new assertions; existing OCR sessions expire within 8 hours (no live cross-host account polling in v1 of this design).

## 6. Isolation

- Persist users, sessions, jobs, and audit rows in a local SQLite file (for example `web.sqlite3` under the work directory).
- Job files live under a per-user directory. List/download/delete must check owner, not just job id.
- The OCR worker remains global and single-threaded. The UI may show an anonymous queue position, never another user's filename.
- Restart recovery: reload jobs from SQLite + disk; do not leak other users' tasks into the page.

## 7. Out of scope for this note

- Implementing the IdP side in this repository
- Cross-host live session revocation
- Multi-worker OCR on small hosts
- Shipping a real SSO secret or production inventory

Related local files: `src/bankocr/server.py`, `deploy/systemd/bankocr-server.service`, `deploy/nginx/ocr.example.com.conf`.
