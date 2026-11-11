# Contributing to Aesop Studio

Aesop Studio is a private, owner-operated project. This document describes the **light path** the owner approved for changes.

## Roles

Appointments (owner, 2026-11-11): **OpenAI** is Director, **Claude** is Orchestrator, **Cursor** is Foreman, and the **local LLM** (Local Warden) is Warden. Antigravity is Secretary. `docs/PROJECT-COMMUNICATIONS.html` records the details and the earlier arrangement.

## Workflow

1. **Writer:** work in your own **git worktree** on a branch named `<provider>/<topic>` (examples: `cursor/repo-e2e-20261026`, `codex/browser-v2-antigravity`).
2. **Checks:** run the full offline test suite and any live checks the change needs, and record the results in the PR.
3. **Independent review:** a reviewer who did not write the change. Exact-head gate verdicts come from the Warden. Nobody approves or accepts their own work.
4. **Merge:** `main` is protected and needs green CI plus one approving review. Merge, deployment and credentials stay with the owner.

**Repairs:** whoever finds a defect fixes it within their own authority (owner policy, 2026-11-08). The Foreman issues a repair order only when the finder cannot solve it, or after three failed, evidence-based attempts on the same issue.

Record rulings in commit messages and under `docs/` when they affect behavior.

## Running tests locally

```powershell
.\scripts\run_tests.ps1
```

Or manually:

```powershell
$env:AESOP_PROBE_OFFLINE = "1"
$env:AESOP_SIMULATED_ROUTE = "1"
python -W ignore -m unittest discover -s tests -p "test_*.py"
```

Optional syntax checks:

```powershell
node --check static/app.js
```

On branches that include the browser v2 Chrome extension, also run `node --check` on `extension/**/*.js` and `node tests/js/*.mjs` when present.

CI runs the same unittest command on **Windows and Ubuntu** with Python 3.11, 3.12, and 3.14, plus the Node checks above.

## Hard rules

- **Stdlib only** for the server (`aesop_studio/`). Helpers may use `.venv`; the extension is plain JS.
- **Loopback only** (`127.0.0.1`). Never commit credentials; keep `aesop_studio/security.py` `redact()` patterns current for new providers.
- **No owner data deletion** — archive instead.
- **Metered routes** stay off until the owner sets a limit or mission permit.

## Project context

See `docs/PROJECT-BRIEFING-20261026.md` for architecture, open items, and today’s `main` history.
