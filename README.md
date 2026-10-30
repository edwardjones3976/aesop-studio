# Aesop Studio

[![CI](https://github.com/edwardjones3976/aesop-studio/actions/workflows/ci.yml/badge.svg)](https://github.com/edwardjones3976/aesop-studio/actions/workflows/ci.yml)

A personal, local-first browser workspace for AI projects on Windows. Open a project, choose its provider, attach files, chat (and optionally work in the project folder from the same composer), inspect and save the results, then close and resume later.

## Quick start

```powershell
git clone https://github.com/edwardjones3976/aesop-studio.git
cd aesop-studio
.\start.ps1    # binds 127.0.0.1:8765 or the next free port; opens the one-time sign-in link
```

`.\open.ps1` opens a fresh sign-in link when Studio is already running. `.\stop.ps1` stops the server started by `start.ps1`. Data stays in `%LOCALAPPDATA%\AesopStudio`.

## Architecture

Python **stdlib-only** server (`aesop_studio/`), vanilla JS UI (`static/`), loopback auth, supervised agent tasks, research, and evidence. Full map, process, and open work: **`docs/PROJECT-BRIEFING-20261026.md`**.

**Browser:** `main` ships browser **v1** (Playwright over a separate Chrome profile). **Browser v2** (MV3 extension in your normal Chrome profile, DOM-first agent) lives on branch `codex/browser-v2-antigravity` until repair 4 lands.

- **Chat (includes folder work):** project conversations through every **usable** in-app route (Codex, Claude Code, Cursor, Antigravity, Copilot CLI after **Verify**, optional Codex API, and the offline test adapter). Each message can pick a provider in the composer. **Work in this folder** (Ctrl+2) is the same composer: off is a chat answer; on runs a supervised agent in the project folder (live output and changes in the inspector). Cursor / Antigravity / Copilot CLI remain chat-only. You can preview the exact context before it is sent. Interrupted folder work is reconciled on restart and never replayed automatically.
- **Plan (its own workspace tab):** each project has its own checklist and focus line. They are never mixed across projects. Open Plan on the left rail. The inspector can still show a short copy of the same checklist.
- **Editor (its own workspace tab):** a small folder-and-text editor for the open project's files (read, save, then Ask / Learn / Practice / Review / Work into Chat). Not VS Code; no extra packages. Saves require the same folder-work acknowledgement as Chat. The inspector's Editor tab opens the same editor.
- **Research & Knowledge:** a cited notebook mixing public pages (fetched SSRF-safely) and approved local documents. Exports can include or exclude private sources.
- **Project memory:** authoritative records, source-linked derived summaries, and explicitly promoted shared knowledge. Corrections supersede old records and keep them for provenance.
- **Evidence:** live views of the budget ledger, acceptance matrix, task outcomes and latency samples, plus backup and a restore test.

No dependencies beyond Python 3.11+ (stdlib only). There is no build step and nothing is installed globally.

## Start / stop (Windows)

Double-click **Aesop Studio** on the Desktop (this PC's home). That login app starts Studio if needed and opens a one-time sign-in link in your browser.

```powershell
python tools\login_app.py --install-shortcut   # pin or restore the Desktop shortcut
python tools\login_app.py                      # login window (also recreates the shortcut)
.\open.ps1           # same sign-in without the window
.\start.ps1          # starts on http://127.0.0.1:8765 (or the next free port) and opens the one-time launch link
.\stop.ps1           # stops the server started by start.ps1
```

The server claims its port exclusively. If 8765 is busy, it tries `preferred.port` in the data folder first (the last port that served this library), then the next free port. Project records stay in `%LOCALAPPDATA%\AesopStudio\aesop.db`. A restart or a new port does not delete them. Archive is the way to hide a project; the folder on disk is left in place.

Data lives in `%LOCALAPPDATA%\AesopStudio` (override with `-Data` or `AESOP_DATA`). The server binds to **127.0.0.1 only**. A browser session needs the one-time launch link written to `launch-link.txt` at startup. The sign-in key is stored per browser site, so the launch link is what opens the same library after a port change.

## Providers

| Route | How it is verified | Billing |
|---|---|---|
| `codex` (Codex) | `codex login status` → "Logged in using ChatGPT" | ChatGPT plan quota, $0 incremental |
| `claude` (Claude Code) | `claude auth status` → `authMethod: claude.ai` | Claude plan quota, $0 incremental |
| `openai-api` (Codex API) | `OPENAI_API_KEY` present (value never read into logs/UI) | Metered per token, streamed. Off until you set a monthly limit or turn on the mission permit |
| `cursor` (Cursor) / `antigravity` (Antigravity) / `copilot` (Copilot CLI) | Providers → **Verify** (one tiny live call) | Their own plan quota; read-only ask/plan mode, chat only |
| `grok` (Grok CLI) | installed | Blocked: billing basis not verifiable |
| perplexity / firecrawl | not integrated | Handoff/research only |

Studio never reads credential files. `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` are removed from child-process environments so the CLIs use subscription sign-in. To sign in: `codex login`, `claude auth login`. After that, choose **Providers → Re-verify** in the app.

## Paid OpenAI API route (optional)

This is the only route that costs money. It calls the OpenAI Responses API directly, streams the answer into the chat, and records the exact cost of each request.

1. Create a key at platform.openai.com. **Do not paste it into chat.** Store it yourself:
   `setx OPENAI_API_KEY "sk-..."` in a new terminal, then `.\stop.ps1; .\start.ps1`.
2. In **Evidence → Spend controls**, set a **monthly operating limit**. Or turn on the **mission development permit** to bill the one-time $165 development envelope; it switches off at every restart.
3. In project **Settings**, choose `openai-api` as the provider. Studio always uses `gpt-6.1-sol` at reasoning `medium` ($2/$10 per 1M tokens). `gpt-6-luna` ($0.10/$0.50) and `gpt-6-astra` ($10/$50) stay in the price table and are not offered as a switch. Prices were verified 2026-10-23 from developers.openai.com/api/docs/pricing.

Each request is capped at 2,000 output tokens. Its worst-case cost (input estimate + full output allowance + 10%) is reserved **before** sending, and the request is refused if that would exceed the limit. The actual cost from the API's usage report then replaces the reservation. A request that is cancelled or cut off keeps its reservation as unresolved exposure, because generated tokens may still be billed. Requests use `store: false`. The key is removed from every CLI child process.

## Permissions model

- Each project has one selected root folder. Agent tasks run there as the primary workspace. Drive roots, your home folder, and credential folders are refused.
- **Working folders** (Settings): optional absolute paths where Work tasks may also read and write via each CLI's directory flags (`reference_dirs` in the database). Grok and ZCode get the paths in the prompt only.
- New projects default to allowing attached files on every in-app provider route (research APIs still take no uploads). Older projects keep their transfer policy; use **Allow for X** in the composer or Settings to grant a route.
- Sending attached files to a provider still respects the per-project transfer policy when you change it. The chat text itself goes to the project's provider.
- **Administrator agent tasks** (Claude Code, Codex, Cursor) use each CLI's highest autonomy in agent mode (`bypassPermissions`, `danger-full-access`, `--force`). Worker CLIs keep their normal edit-capable agent flags. Chat mode stays read-only/plan in a temp sandbox.
- Switching away from a project's default provider requires an explicit confirmation. There is no automatic fallback.
- Only one agent writer runs per project at a time. Archiving a project hides it and never deletes files.

## Tests

```powershell
.\scripts\run_tests.ps1          # full suite (~90s), offline — recommended
# or:
$env:AESOP_PROBE_OFFLINE = "1"; $env:AESOP_SIMULATED_ROUTE = "1"
python -W ignore -m unittest discover -s tests -p "test_*.py"
```

`AESOP_PROBE_OFFLINE=1` skips live CLI probes during route discovery (set automatically by `tests/__init__.py` and `run_tests.ps1`). The `SIMULATED` adapter is enabled only with `AESOP_SIMULATED_ROUTE=1` and is never counted as a live provider. Live provider results are recorded in `docs/report.html`.

## Backup / restore

Use **Evidence → Create backup**, or call `aesop_studio.backup.create_backup`. This takes a consistent SQLite snapshot plus the stored files, with a SHA-256 manifest. **Test restore** unpacks the latest backup into `restore-tests/<timestamp>` and verifies hashes, `PRAGMA integrity_check`, and row counts. It never restores over live data. Credentials are not included: run `codex login` / `claude auth login` again on a new machine.

## Model-assisted proposals

Research → **Draft findings** and Chat → **Summarize to memory** ask the project's own provider (one request) to propose cited findings or a derived summary. Proposals stay out of exports and context packets until you **Accept** them.

## Roundtables (live, off by default)

Chat → **Roundtable** / **War Room** configures a multi-provider session from live lane discovery. **Evidence → Spend controls → Live roundtables** must be **On** before compare, preflight **Start**, or a live broker session (the switch is forced **off** at every server restart and auto-off shortly after a session ends).

- **Planning:** save drafts, run preflight, export a planning packet (no providers contacted).
- **Side-by-side compare:** one read-only chat turn per selected speaker (2–4), owner-confirmed, separate from the live broker.
- **Live broker:** concurrent openings and a moderated open floor; read-only chat turns only — nothing said is executed.

Use **Providers → Verify** for Cursor, Antigravity, and Copilot CLI before they count as roundtable speakers.

## Paid review tool

`python tools/paid_review.py --lens stability|security|frontend|visual` runs a bounded, ledgered Codex API review (results in `docs/reviews/`).

## Known limits

- Codex chat runs `-s read-only` in an empty temp folder, but Codex's sandbox can still *read* outside it. Use Claude for chat on sensitive machines.
- Agent tasks join a kill-on-close Windows Job Object just after launch. Anything spawned in that first instant falls back to `taskkill /T`, and the task is marked `EFFECT_UNKNOWN` if output never closes.
- Other servers on 127.0.0.1 receive the session cookie. Processes running as you are inside the trust boundary.
- Usability benefit is unmeasured until you record an owner trial (Evidence → Workflow measurements).

## Repair procedure

Tasks that were running when Studio stopped become `INTERRUPTED` or `EFFECT_UNKNOWN`, and a `repairs` row (`OPEN_FOREMAN`) is opened with a reproducer hash. Review the task's changed files, then resubmit manually if needed. Nothing is replayed automatically. **Evidence → Export packet** writes a formal repair packet (signature, reproducer, contract, allowed paths, tests, scope, budget, rollback, owner) to `foreman-outbox/` for the Director-Orchestrator Foreman.

## Contributing

See `CONTRIBUTING.md` for the light-path workflow, branch naming (`<provider>/<topic>`), and how CI runs tests.

## Docs

- `docs/PROJECT-BRIEFING-20261026.md`: architecture, commits, open items (start here)
- `docs/vision.md`: vision charter and foundation decision record
- `docs/plan.html`: mission planning document
- `docs/report.html`: completion report, generated by `python -m aesop_studio.report`
- `docs/acceptance.json`, `docs/research.json`: the shared evidence model, used by both the dashboard and the report
