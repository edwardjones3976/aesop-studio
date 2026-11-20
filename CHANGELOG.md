# Changelog

All notable changes to this repository are documented here. The server uses calendar versioning tied to `main`; entries below seed from work landed on **2026-10-26**.

## 2026-10-26

- **Reference studies (R-1):** Serialize study finishes per project; no duplicate plan steps (`9a29f04`).
- **Launch:** Exclusive port claim, fall-forward when busy, real server PID in data dir; `start.ps1` / `open.ps1` / `stop.ps1` and `scripts/studio-common.ps1`; login app probes `Server: AesopStudio` (`34c5095`).
- **Repo tidy:** Scratch moved to git-ignored `.scratch/`; Foreman work orders (`1cf4040`).
- **Perplexity:** Metered Orchestrator chat route and Researcher Search upgrade (`6c99527`); key smoke test and access work order (`68184ec`, `1d4070f`).
- **Tests:** Launch-port fall-forward test hardened for adjacent free ports (`2d21fb5`).
- **Docs:** Full project briefing for contributors (`6b841b6` on branch `cursor/repo-e2e-20261026`).

## Unreleased

- **Send-time per-model quota fallback:** Chat/dispatch for multi-model CLI routes (Antigravity first) uses the same `MODEL_PREFERENCES` / catalog / `record_model_quota` path as Verify (WO-20261027-002). On 429/RESOURCE_EXHAUSTED, Supervisor tries the next eligible model in-task, records `model_in_use` / `models_exhausted` on the task checkpoint, and parks `UNAVAILABLE` only when every eligible model fails; auth/timeouts do not advance. See `AGENTS.md` quota rule.
- **Launch port CI:** Windows port-claim test probes with `SO_EXCLUSIVEADDRUSE` and falls forward past Hyper-V/HTTP.sys excluded neighbours (fixes `test_busy_port_moves_to_the_next_free_one` flake on windows-latest). Probe/`make_server` attempts stay within TCP 65535; deterministic held-port test covers fall-forward regressions.
- **Arena Run both (free routes):** Dual-lane dispatch for included/local/simulated lanes via existing chat APIs (`POST /api/projects/{pid}/arena/run`). Metered lanes refused with no ledger reserve; UI enables the button only when both lanes are eligible; Stop cancels both tasks (pending dispatch via `cancelPending`, honors `cancel_signalled`, keeps Run both off until cancels finish); tab remount preserves/resumes an in-flight run per project; poll follows `retried_as`, serializes ticks (`pollBusy`), and does not treat HTTP poll errors as task failure; partial second-lane send failure cancels the first task. See `docs/arena-compare.md`.
- **Arena Copilot fixes:** Metered/`READY_METERED_DISABLED` routes are not reported as free; they are selectable for estimate comparison; cost and demo fetches ignore stale responses (`costGen` / `viewGen`).
- **Arena compare tab:** Left-rail **Arena** workspace with dual lanes, per-lane provider pickers, cost estimates (`/api/arena/*`), and four interactive demo fixtures (Alpine, Lost Valley, Deep Time, Optical). See `docs/arena-compare.md`.

## Unreleased (prior branches)

- **testrun:** Prefer `python3` on PATH when `python` is absent (Linux offline suite).
- **Prompt generator:** Offline idea → structured prompt scaffolds (modes, ready/reusable, variables, Studio route hints) via Chat “Shape prompt”; optional enhance on included/local/simulated chat routes only (`aesop_studio/prompt_generator.py`).
- GitHub Actions CI (Windows + Ubuntu, Python 3.11/3.12/3.14).
- Contributing, security, issue/PR templates, `CODEOWNERS`, editor and line-ending hygiene.
- `LICENSE` (all rights reserved) and `docs/REPO-SETTINGS.md` per Foreman ruling.
- Test fixes: Windows-only port-claim tests, CI retries for flaky roundtable live tests, browser guard test without a local `.venv`.
