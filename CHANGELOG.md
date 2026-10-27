# Changelog

All notable changes to this repository are documented here. The server uses calendar versioning tied to `main`; entries below seed from work landed on **2026-10-26**.

## 2026-10-26

- **Reference studies (R-1):** Serialize study finishes per project; no duplicate plan steps (`9a29f04`).
- **Launch:** Exclusive port claim, fall-forward when busy, real server PID in data dir; `start.ps1` / `open.ps1` / `stop.ps1` and `scripts/studio-common.ps1`; login app probes `Server: AesopStudio` (`34c5095`).
- **Repo tidy:** Scratch moved to git-ignored `.scratch/`; Foreman work orders (`1cf4040`).
- **Perplexity:** Metered Orchestrator chat route and Researcher Search upgrade (`6c99527`); key smoke test and access work order (`68184ec`, `1d4070f`).
- **Tests:** Launch-port fall-forward test hardened for adjacent free ports (`2d21fb5`).
- **Docs:** Full project briefing for contributors (`6b841b6` on branch `cursor/repo-e2e-20261026`).

## Unreleased (this branch)

- GitHub Actions CI (Windows + Ubuntu, Python 3.11/3.12/3.14).
- Contributing, security, issue/PR templates, `CODEOWNERS`, editor and line-ending hygiene.
- `LICENSE` (all rights reserved) and `docs/REPO-SETTINGS.md` per Foreman ruling.
- Test fixes: Windows-only port-claim tests, CI retries for flaky roundtable live tests, browser guard test without a local `.venv`.
