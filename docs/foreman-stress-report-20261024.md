# Aesop Studio — stress-run report and ruling requests

**From:** director-orchestrator-cwd session (Claude Opus 4.7, max effort), Claude Code
**Date:** 2026-10-24
**Scope:** Aesop Studio (`C:\Users\edwar\Claude\Projects\Aesop-Studio`) — the local-first browser AI workspace. Not a Director mission artifact; dropped here because this Foreman MCP's two write roots are the only ones reachable through its write tool.
**Branch head after this run:** `aaf564c` — "Harden study feature and surrounding helpers after a stress run"

## 1. What this session shipped

Three owner-authorized features landed on `main`:

- `776dc0c` — New project dialog: folder autocomplete via `GET /api/fs/dirs`, create-folder-named-after-project mode, OK button disabled until the location exists, remembered last location. Replaces an unwieldy pop-out the owner had multiple folder-path issues with.
- `3a32d2c` / `c2bbffd` / `1b2842d` — Reference studies: a provider (Claude Code or Codex) statically inspects a registered reference application (Cursor, VS Code, Perplexity, Antigravity, LM Studio) through the R.E.A. MCP server (morluto/rea, MIT, v6.7.0, pinned) and files evidence-backed findings and plan steps. Read-only sandbox, one-time acknowledgement, no shell/edit tools; the registry refuses system/credential/home/drive roots; Studio's own `studies/<id>` folder as cwd; R.E.A. archived in `~/Documents/REA-Archive` (git mirror, bundle with SHA-256, npm pack).
- `aaf564c` — The hardening pass this packet reports on.

Owner has run two pilot studies through this UI:

- **Cursor composer** (Claude Code via R.E.A., ~4 minutes): 10 findings, 10 steps covering drafts with promise-queue + epoch, pending/sent/failed message status with Retry/Edit, transactional resubmit, paste order, attachment table.
- **VS Code change review** (Claude Code via R.E.A., ~4 minutes): 11 findings, 10 steps covering a hash-addressed blob store for originals, per-request checkpoints with undo/redo, version-token 409s on stale diffs, Keep/Undo per-file + all-files, hunk nav, session rehydration from SQLite.

## 2. Stress battery

Harness: 11 scenarios run against disposable Studio data dirs under `%TEMP%\aesop-stress-*\d`, each threaded with `ThreadPoolExecutor`, nothing touching the owner's live Studio or its database. Simulated route (`AESOP_SIMULATED_ROUTE=1`, `AESOP_PROBE_OFFLINE=1`) so no network, no provider spend, no sign-in.

Scenarios, each a realistic failure mode the pasted strategy document flagged (project continuity, interrupt-and-resume, inspectable agent work, source-linked research, provider readiness):

1. `ref_registry_race` — 20 concurrent `study.add_ref` on one folder.
2. `parallel_studies` — 20 simultaneous `study.start` against one project.
3. `interrupt_resume_multi` — 5 agent writers, kill Supervisor mid-run, reconcile.
4. `interrupt_resume_study` — a RUNNING study, kill Supervisor, reconcile.
5. `plan_churn` — 300 concurrent `plan.add` across 8 workers.
6. `study_refusals` — every refusal path (bad path, no ack, empty topic, missing ref, non-study provider).
7. `parser_fuzz` — 9 malformed JSON inputs including a 2 MB garbage payload and a 5000-finding JSON.
8. `argv_safety` — reference paths containing shell metacharacters (`;`, backtick, `&`, `$()`, embedded newline).
9. `redactor_leaks` — all five key shapes the Studio handles.
10. `rehydration_hang` — a study whose watcher thread "dies" mid-finish.
11. `scope_errors_coverage` — `validate_root` on SystemRoot, ~/.ssh, home.

Full suite: 174 tests. 173 pass. One pre-existing load-sensitive flake (see §4).

## 3. Issues found and fixed in-session (6)

All fixes land on `main` at commit `aaf564c` with regression tests under `tests/test_study.py::TestStressFixes` and `TestRedactorNewShapes` (33 tests pass locally).

| # | Severity | File | What | Fix |
|---|---|---|---|---|
| 1 | **HIGH (security)** | `aesop_studio/security.py` | Redactor let `pplx-...` (Perplexity) and `fc-live-.../fc-...` (Firecrawl) API keys through unchanged. Studio's Researcher reads both from env; keys could survive into logs, study reports, task output. | Added two regexes alongside the existing `sk-` / `sk-ant-` / `gh[pousr]_` patterns. All three shapes now redact. |
| 2 | MEDIUM | `aesop_studio/study.py` (`add_ref`) | 20 concurrent registrations of the same folder admitted 10 rows into the kv list instead of 1. Classic read-modify-write race on a JSON blob. | Wrapped the read, dedupe check, and write in `store.write_lock`. Stress now shows 1 success, 19 duplicate-refused. |
| 3 | MEDIUM | `aesop_studio/study.py` (`list_studies`), `aesop_studio/server.py` | A study row stayed `RUNNING` forever if the watcher thread died mid-finish (crash or restart). | Added lazy-finish pass in `list_studies(sup=, svc=)`, mirroring how `plan.list_items` reconciles `task_ref` state. Server endpoint passes `sup`/`svc` through. |
| 4 | MEDIUM | `aesop_studio/study.py` (`start`) | A caller passing `provider="grok"` silently fell back to Simulated instead of refusing. Owners should know Grok, Z.ai, Perplexity, Firecrawl etc. cannot run reverse-engineering tools. | Explicit `ValueError`: "`<route>` cannot run reference studies; pick Claude Code or Codex". |
| 5 | HIGH (pre-existing) | `aesop_studio/plan.py` (`add`) | Pre-existing race between the `MAX_ITEMS` count check and the INSERT: 300 concurrent `plan.add` ended with 207 items (cap is 200). The study feature does not aggravate it, but stress surfaced it. | Count-check and INSERT share one `store.write_lock` critical section. Stress now shows 200 added, 100 refused, final 200. |
| 6 | LOW | `aesop_studio/tasks.py` (`reconcile`) | An interrupted study opened a repair packet, even though a study is read-only (`--permission-mode default` with no Bash/Edit/Write/MultiEdit/WebFetch — the agent cannot have made disk changes). | Treat `study` like `chat` in the repair branch. Unknown modes stay conservative. |

Verified by rerunning the stress harness: 11/11 scenarios green; the only remaining print-out is a low-severity dedupe question (see §5).

## 4. Pre-existing items for the Foreman to log, not for me to fix

- `tests.test_roundtable_live.TestResearcher.test_switch_turns_off_after_conclusion_and_history_kept` — fails under full-suite load (173/174), passes in isolation and when its file runs alone. Same flake class as `test_rt05_concurrent_fanout_fanin_with_causal_ids` noted in prior session work. Not caused by any code I touched. Suggest tracking as a known-flaky.

## 5. Ruling requests (one item)

### R-1. Dedupe policy for plan items that come from different studies

Scenario: 20 simultaneous reference studies each emit two identical steps. Current `study.finish` snapshots `plan.list_items`, finds no match, and inserts. Concurrent finishes see the same snapshot and both insert — the plan ended with 4 duplicates after 20 studies instead of 2.

- **Fix A** (owner-friendly, mild loss of signal): case-insensitive uniqueness inside `plan.add`. Same step from a second study gets a `source` update rather than a new row.
- **Fix B** (more honest about provenance): serialize `study.finish` with a per-project `threading.Lock` keyed on `pid`. Steps are still unique per batch; two studies that word a step the same still produce only one row.
- **Fix C** (do nothing): accept small duplication after a flood of concurrent identical studies — in normal use a single owner starts studies serially.

**Recommendation: Fix B.** It preserves "one step row per unique wording per project" without making `plan.add` quietly swallow owner input from the Draft or manual Add paths.

I did not implement any of these; this is UX scope and I want the Foreman call.

## 6. Status at close

- Live Studio restarted on commit `aaf564c`, PID 58560, listening on `127.0.0.1:8765`, serving status 200.
- Plan tab on the "Aesop Studio design review" project shows two filed studies with 20 total step rows and findings panels.
- R.E.A. registered globally for Claude Code + Codex with backups preserved; archive copy in `~/Documents/REA-Archive`.
- Perplexity Researcher route still blocked by placeholder `pplx-your-key-here` env var — owner action still outstanding.
- GitHub sign-in in the Studio Chrome window for private-repo visibility — owner action still outstanding.

No destructive changes. No external messages sent on the owner's behalf. No provider spend without owner permission (pilot studies ran on the owner's Claude Code plan quota, started by the owner through the UI).
