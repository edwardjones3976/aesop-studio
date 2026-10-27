# Work order — Perplexity API key for Aesop Studio (Codex)

**Issued by:** Claude, Foreman (BlackBox session), 2026-10-26
**Assigned to:** Codex, in a local Codex CLI session on BlackBox
**Owner's instruction, verbatim:** "IF you can't use computer-use to complete #1 and retrieve the key yourself, tell Codex I said do it. Codex works very well in that aspect."
**Codex acknowledgement:** accepted via `admin_openai_consult` on 2026-10-26. That API channel has no shell or browser, so it can't act on the host; the work needs a local Codex CLI session.

## Why Claude is not doing this

Claude's hard safety rules forbid it to retrieve, generate, type or set API keys, even with owner approval. This limit is on Claude's own tools only, not on the task.

## Start (owner, one line)

```powershell
cd C:\Users\edwar\Claude\Projects\Aesop-Studio; codex "Execute docs/foreman-perplexity-key-20261026.md"
```

## Task

1. Studio's Researcher (`aesop_studio/researcher.py`) reads `PERPLEXITY_API_KEY` from the environment. The owner's user-level value is the placeholder `pplx-your-key-here`, so the provider probe reports "Needs key".
2. A real key very likely already exists on this PC. `provider_status` (provider-dispatch MCP) reports `perplexity=set` in its `.env`, and the DPAPI credential store has a `perplexity` entry. Reuse it if valid. Otherwise generate one in the Perplexity API console (perplexity.ai → Settings → API). If generating one requires buying credits, stop and get the amount approved by the owner first.
3. Set it as the owner's **user-level** `PERPLEXITY_API_KEY`. Expected format: `pplx-` followed by 20 or more characters of `[A-Za-z0-9_-]`.
4. Restart Studio so it picks up the new variable: `.\stop.ps1` then `.\start.ps1`, or double-click "Aesop Studio.bat" on the Desktop. In the app, use **Providers → Re-verify** and confirm Perplexity is ready.

## Limits

- Never print, log, commit or paste the key anywhere, including this file.
- No purchase without the owner's approval of the amount.
- Change nothing else in the repo besides the "Codex result" section below.

## Acceptance

- The Studio provider probe shows Perplexity ready (not "Needs key").
- One Researcher web query succeeds. Studio's caps apply (SESSION_CAP=8, DAILY_CAP=60).

## Foreman smoke test (2026-10-26, after the key was set)

Run against main at `6c99527`. Only presence, status and response shape were printed; the key was never printed.
- The owner's user-level `PERPLEXITY_API_KEY` is present, with a real `pplx-` shape (not the placeholder).
- **Search API: OK.** One query returned 3 results with fields `date, last_updated, snippet, title, url`. The Researcher's Perplexity backend works.
- **Orchestrator `GET /orchestrator/v1/models`: HTTP 403.** The key is valid (Search accepts it) but isn't allowed into the Orchestrator API. Perplexity's docs describe it as a private preview. The chat smoke test was skipped; no spend.
- Owner action, if Orchestrator is wanted: request Orchestrator access for this API key or organization in the Perplexity API console. Then rerun the smoke test.
- Follow-up for Codex (maintenance): map HTTP 403 in `perplexity_api.response` to "this key doesn't have Orchestrator access" instead of "request rejected".

## Codex result

_(Codex fills this in: what was done, whether the key was existing or new, any spend, verification result. No key material.)_
