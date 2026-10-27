# Aesop Studio — instructions for every agent working in this repository

Read `docs/PROJECT-BRIEFING-20261026.md` first (architecture, process, hard rules). Owner policy: no Submission Tag Headers, contribution tags/envelopes or contribution-acknowledgment procedures.

## Hard rules (repeated here because they are easy to break)

- The server is Python 3.11+ **stdlib-only**. Helpers may use `.venv`; the browser extension is plain JS.
- Loopback only. No credential is read into Studio, logged, printed or committed. `aesop_studio/security.py::redact` must cover every provider key shape you add.
- Agents never type into password fields, solve CAPTCHAs or make purchases. Every agent action is visible and stoppable.
- Metered routes reserve the worst-case cost before sending and stay off until the owner sets a limit or turns on the permit.
- Never delete owner data; archive instead.

## Per-model quota is not provider exhaustion — owner rule, 2026-10-26

A 429 / RESOURCE_EXHAUSTED / "quota reached" that names a model, or arrives while one pinned model is in use, is a **model** fault, never a provider fault. Before any code or report treats a provider as exhausted or unavailable: list the provider's models from its own CLI (e.g. `agy models`), retry the same minimal call on the next eligible model, and report "model X exhausted (resets <time>); using Y". A provider is exhausted only when **every** eligible model fails with the same quota fault.

Worked case: on 2026-10-26 Antigravity's default model (`gemini-4-argon-high`) returned "Individual quota reached … Resets in 81h" while `gemini-3.8-flash-low` answered immediately. Studio's verify marked the whole route `UNAVAILABLE`, and the lane was wrongly parked. Studio's multi-model routes (antigravity first; copilot, zai, grok follow the same design) must keep an ordered model list, fall back automatically on a per-model quota fault, record `model_in_use` and `models_exhausted` (with reset text), show them in the Providers panel, and report `UNAVAILABLE` only when every model fails. See WO-20261027-002, Part B.

## Process (owner-approved light path)

Writer on its own worktree branch → Foreman live check + full suite (`scripts\run_tests.ps1`) → landed under the writer's identity → eligible non-author review → PR → merge. `main` is protected: green CI and one review required.
