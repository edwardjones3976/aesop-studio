# Arena compare (Studio tab)

Dual-lane model comparison shell **inside Aesop Studio** — left rail tab **Arena**, same nav as Chat / Build / Memory / Saved.

## Open it

1. Start Studio (`start.ps1` / launch link) on loopback.
2. Open any project.
3. Click **Arena** in the left rail (or **Ctrl+4**, or command palette → “Go to Arena”).

## What ships

- **Split panes** — Lane A / Lane B.
- **Lane pickers** — each lane independently selects any Studio route from `/api/routes` (codex, claude, cursor, antigravity, grok, zai, director-lmstudio/ollama, simulated, etc.), including `READY_METERED_DISABLED` so metered estimates can be compared while spend stays off. Preferences persist per browser.
- **Cost readout** — per-lane estimate from `/api/arena/estimate` (and bundled `/api/arena/compare`). Uses ledger-aligned billing basis / state: included/local/simulated → `$0`; any `METERED` state (even when `billing_basis` still says subscription) is never reported as free; Codex API → verified price-table ceiling for a reference brief; other metered routes → honest “unknown” note. Stale estimate responses are ignored via a cost-request generation.
- **Run both (free routes)** — enabled only when **both** lanes are included / local / simulated (`READY_INCLUDED`, `READY_LOCAL`, `SIMULATED`, or non-metered `billing_basis` in `subscription_included` / `local`). Dispatches two chat turns through the existing `Services.send` path (same reserve/settle as Chat). Metered / `READY_METERED_DISABLED` lanes keep the button disabled or return 400 with a clear note — **nothing is reserved** for a refused lane. Results poll side-by-side; Stop cancels both local process trees (remote stop is not provable). Stale run replies are ignored via `runGen` / `viewGen`.
- **Loadable demos** (interactive fixtures, not screenshots-only): Alpine Atlas, Lost Valley, Deep Time Atlas, Optical Gallery. Plain canvas/CSS under `static/arena/`; no new Python deps, no CDN (CSP `script-src 'self'`).

## Out of scope (follow-up)

- Metered dual-run even with owner limit/permit.

## APIs

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/arena/demos` | Demo catalog + live-dual feature flag |
| GET | `/api/arena/estimate?route=&demo=` | One-lane cost readout (`live_dispatch` when free) |
| GET | `/api/arena/compare?a=&b=&demo=` | Catalog + both lane estimates (`live_dual_generation` when both free) |
| POST | `/api/projects/{pid}/arena/run` | Dual free-route dispatch (`a`, `b`, `demo`, optional `prompt`) → 202 with both task/message ids; 400 if either lane ineligible |

## Hard rules

Loopback only; redact; archive don’t delete; metered off until permitted. Arena estimates never invent credentials. Run both never reserves ledger for a refused lane.
