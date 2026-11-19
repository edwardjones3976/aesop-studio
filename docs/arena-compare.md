# Arena compare (Studio tab)

Dual-lane model comparison shell **inside Aesop Studio** — left rail tab **Arena**, same nav as Chat / Build / Memory / Saved.

## Open it

1. Start Studio (`start.ps1` / launch link) on loopback.
2. Open any project.
3. Click **Arena** in the left rail (or **Ctrl+4**, or command palette → “Go to Arena”).

## What v1 ships

- **Split panes** — Lane A / Lane B.
- **Lane pickers** — each lane independently selects any Studio route from `/api/routes` (codex, claude, cursor, antigravity, grok, zai, director-lmstudio/ollama, simulated, etc.). Preferences persist per browser.
- **Cost readout** — per-lane estimate from `/api/arena/estimate` (and bundled `/api/arena/compare`). Uses ledger-aligned billing basis: included/local/simulated → `$0`; Codex API → verified price-table ceiling for a reference brief; other metered routes → honest “unknown” note. **Nothing is reserved or dispatched.**
- **Loadable demos** (interactive fixtures, not screenshots-only): Alpine Atlas, Lost Valley, Deep Time Atlas, Optical Gallery. Plain canvas/CSS under `static/arena/`; no new Python deps, no CDN (CSP `script-src 'self'`).

## What v1 does not do

- Live dual generation (“Run both”) is disabled until owner metered limits / permit and existing chat APIs are wired without unmetered spend.

## APIs

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/arena/demos` | Demo catalog + live-dual flag |
| GET | `/api/arena/estimate?route=&demo=` | One-lane cost readout |
| GET | `/api/arena/compare?a=&b=&demo=` | Catalog + both lane estimates |

## Hard rules

Loopback only; redact; archive don’t delete; metered off until permitted. Arena estimates never invent credentials.
