# Work order — request Perplexity Orchestrator access (Codex)

**Issued by:** Claude, Foreman (BlackBox), 2026-10-26
**Assigned to:** Codex, in an interactive Codex CLI session on BlackBox, supervised by the owner
**Owner's instruction, verbatim:** "Have Codex request Orchestrator access for my key"

## Why

The owner's Perplexity API key works for the Search API: the Foreman's smoke test returned 3 results. `GET https://api.perplexity.ai/orchestrator/v1/models` returns **HTTP 403** for the same key. Perplexity's docs state "Orchestrator API is in private preview" (https://docs.perplexity.ai/docs/router/quickstart). The API platform page states "Some APIs, including Orchestrator, require separate access approval" (https://www.perplexity.ai/api-platform). Aesop Studio already has the Orchestrator route on `main` (`6c99527`), off until access is granted and a monthly limit is set.

## Task

1. In the owner's signed-in Perplexity API console (console.perplexity.ai, or the API settings in their open Edge tab), find how to request Orchestrator (private preview) access: a request or waitlist button, form or contact path. Start from https://www.perplexity.ai/api-platform and the Orchestrator docs above.
2. Request access for the owner's account or organization and API key.
   - Use plainly true answers.
   - Use case: "Aesop Studio, a personal local-first AI workspace that routes chat to frontier models through one key, with per-request spend reservation and a monthly limit."
   - Expected volume: low, single owner.
3. **Before submitting,** show the owner the exact form contents in this window and get their OK. If the form asks to accept new terms, or to buy, upgrade or add a payment method, stop and get the owner's approval of exactly that first.
4. Never print, paste or log the API key.

## Report

Fill in "Codex result" below:
- where access was requested;
- what was submitted (no key material);
- the confirmation or reference shown;
- the expected wait, if stated.

When access is granted, rerun the Foreman's smoke test. The models call should return 200, and one tiny chat should complete.

## Codex result

_(Codex fills this in.)_
