# Security

## Model

Aesop Studio is **local-first** and **loopback-only**:

- The Python server binds to `127.0.0.1` only.
- Session auth uses a one-time launch link, session cookie, CSRF tokens, and optional `X-Aesop-Key`.
- Project data lives under `%LOCALAPPDATA%\AesopStudio` (or `AESOP_DATA`); it is never committed.
- The app does not read credential files into logs or the UI. Child processes have billing-related environment variables stripped.

Agents are supervised: no password fields, CAPTCHAs, or purchases; actions are visible and stoppable.

## Reporting

This is a **private** repository operated by the owner. If you have access and find a security issue:

1. **Do not** open a public issue with exploit details or secrets.
2. Contact the repository owner directly (GitHub `edwardjones3976` or your established channel).
3. Include steps to reproduce, impact, and any suggested fix.

There is no bug-bounty program.

## Development

- Run CI’s secret scan locally before pushing: `python scripts/ci_secret_scan.py`.
- Never paste API keys into chat, commits, or PR descriptions. Use `setx` / OS secret storage and restart Studio.
