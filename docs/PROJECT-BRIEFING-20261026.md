# Aesop Studio — full project briefing (for Cursor and Codex)

**From:** Claude, Foreman (BlackBox), 2026-10-26. **Owner:** Edward Jones (GitHub `edwardjones3976`).
Owner policy: no Submission Tag Headers, contribution tags/envelopes or contribution-acknowledgment procedures, for any provider or project.

## What it is

A personal, local-first browser workspace for AI projects on Windows. One Python 3.11+ **stdlib-only** server (no pip dependencies, no build step) binds `127.0.0.1` only and serves a single-page UI. The owner opens a project (one folder), picks a provider, chats (folder work is a toggle on the same composer), keeps a plan that belongs only to that project, edits files in a small in-app editor, researches with cited sources, and inspects results. Everything stays on the owner's PC.

- Repo: https://github.com/edwardjones3976/aesop-studio (private; `main` at `2d21fb5`). Local: `C:\Users\edwar\Claude\Projects\Aesop-Studio`.
- Data: `%LOCALAPPDATA%\AesopStudio` (SQLite `aesop.db` + files). Never committed.
- Run: `.\start.ps1` (tries 8765, falls forward to the next free port; writes `server.port` and `server.pid`), `.\open.ps1` (fresh one-time sign-in link), `.\stop.ps1`. Desktop launcher: `Aesop Studio.bat`.
- Tests: `.\scripts\run_tests.ps1` (offline, simulated routes; ~4 min; 194 tests on the browser branch, 183 on `main`). Env for tests: `AESOP_PROBE_OFFLINE=1`, `AESOP_SIMULATED_ROUTE=1`. pytest is installed in `.venv` but the suite is `unittest`.

## Architecture (where things live)

| Area | Files | Notes |
|---|---|---|
| HTTP server, routes, auth | `aesop_studio/server.py` | Session cookie + one-time launch code + CSRF + `X-Aesop-Key`; Host/Origin checks; CSP. Exclusive port bind (`SO_EXCLUSIVEADDRUSE`). |
| Providers | `providers.py`, `openai_api.py`, `perplexity_api.py`, `research_routes.py` | CLI routes (codex, claude, cursor, antigravity, copilot, grok, zai) verified by live probe; metered API routes (openai-api, perplexity-orchestrator) gated by the ledger. `BILLING_ENV` keys are stripped from child processes. |
| Spend | `ledger.py` | Reserve worst-case cost before send; settle from real usage; cancelled/cut-off keeps exposure; monthly limit or mission permit required. |
| Agent tasks | `tasks.py` (Supervisor), `winjob.py` | One writer per project; job-object process trees; reconcile on restart; never replay. |
| Research | `researcher.py` | Firecrawl first, then Perplexity Search (multi-query, dedupe, filters); SESSION_CAP 8, DAILY_CAP 60. |
| Reference studies | `study.py` + R.E.A. MCP | A provider inspects an installed app read-only and files findings + plan steps. |
| Plan / notebook / memory | `plan.py`, `derive.py`, `followup.py`, `team.py`, `roundtable*.py` | |
| Browser (v1, on main) | `browser.py`, `browser_worker.py`, `browse_agent.py` | Playwright over CDP 9222 on a second Chrome profile; screenshot polling. Being replaced. |
| Browser (v2, branch) | same files + `extension/` (MV3) + `tests/js/*.mjs` | Chrome extension in the owner's normal profile, paired by token; live DOM-first panel; DOM-first agent. |
| UI | `static/index.html`, `app.js` (~290 KB), `app.css` | Vanilla JS, no framework. |
| Security helpers | `security.py` | `redact()` masks sk-/sk-ant-/gh*/pplx-/fc- keys; `validate_root()` refuses drive roots, home, credential dirs. |
| Tools | `tools/login_app.py` (tk login window + desktop shortcut), `tools/ui_a11y.py` | |

## Today's commits on `main` (2026-10-26)

- `9a29f04` R-1 ruling (Fix B): study finishes serialized per project; no duplicate plan steps.
- `34c5095` Launcher: exclusive port, fall-forward, real server pid; `start/open/stop.ps1` + `scripts/studio-common.ps1`; login app probes Studio by its `Server:` header.
- `1cf4040` Repo tidy (scratch to git-ignored `.scratch/`) + Foreman work orders.
- `6c99527` (OpenAI Codex) Perplexity Orchestrator metered route + Researcher Search upgrade; 27 tests.
- `68184ec`, `1d4070f` Perplexity key smoke test (Search OK; Orchestrator 403 = no preview access yet) and the access work order (Codex emailed Perplexity; no grant yet).
- `2d21fb5` Launch-port test hardened.

## Branches not yet on `main`

- `codex/browser-v2-antigravity` (`bb71047`): browser v2 by Gemini Antigravity, rounds 1–3. Live status: logins ✓, agent ✓, safety ✓, tests ✓ (194), frames ✓; **ack latency ✗** (one action in ~4 costs ~1.55 s). Root cause: the extension's poll and frame push share one HTTP/1.1 connection; repair order 4 (`docs/foreman-browser-v2-20261026.md`, round log) moves frames to pull and separates lanes. In progress.
- `codex/perplexity-orchestrator` (`6c99527`): already fast-forwarded into `main`; branch can be deleted.

## Open items

1. Browser v2 repair 4 → live retest → land on `main` (owner must reload the extension once).
2. Perplexity Orchestrator access: pending Perplexity; route stays off. Codex follow-up: map HTTP 403 to "no Orchestrator access".
3. Blacktop (owner's second PC): clone from GitHub; owner runs `codex login` / `claude auth login` there.
4. Known flaky test: `test_rt05_concurrent_fanout_fanin_with_causal_ids` (timing); passes alone.
5. No CI, no branch protection, no CONTRIBUTING, no issue/PR templates, no CHANGELOG yet (Cursor order).

## Process for this project (owner-approved "light path")

Writer on its own worktree branch → Foreman live check + full suite → land under the writer's identity → eligible non-author review (Foreman may review if only assisting) → fast-forward `main` → push. Rulings are recorded in commit messages and `docs/`. Director-Orchestrator rules (Warden, register, merge_preflight) do **not** apply here.

## Hard rules

- Server stays stdlib-only. Helpers may use `.venv`; the extension is plain JS.
- Loopback only. No credential is read into Studio, logged, or committed. `redact()` covers key shapes; keep it updated for new providers.
- Agents never type into password fields, solve CAPTCHAs, or make purchases. Every agent action is visible and stoppable.
- Metered routes reserve before send and stay off until the owner sets a limit.
- Never delete owner data; archive instead.
