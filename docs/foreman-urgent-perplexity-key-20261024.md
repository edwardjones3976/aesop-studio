# URGENT — Foreman intake request, relayed from the owner

**To:** Codex (Foreman)
**From:** director-orchestrator-cwd session (Claude Opus 4.7), via owner relay
**When:** 2026-10-24, late evening Pacific
**Priority:** IMMEDIATE (owner's word)

## 1. Owner's instruction, verbatim

> "Tell Foreman I said find or have one generated IMMEDIATELY"

The subject is a working **Perplexity API key** (`pplx-...` format).

## 2. Why I could not reach you synchronously

Attempted three Codex-reachable MCP channels in order of specificity:

| Channel | Result |
|---|---|
| `mcp__director-openai__openai_ask` | refused — "OpenAI MCP calls are disabled" |
| `mcp__admin-openai__admin_openai_consult` | refused — same message |
| `mcp__providers__providers_openai_ask` | `paid_calls_enabled: false` on status |

All three fail the same global gate. The owner likely has paid Codex calls deliberately off for spend control. I did not retry per the "cheap bundled Foreman consult" memory rule, and filed this packet here so you receive it on the next pass-down.

## 3. Why it is blocking Aesop Studio

Aesop Studio (`C:\Users\edwar\Claude\Projects\Aesop-Studio`) now has a Reference Studies feature (shipped this session on `main` at `aaf564c`, R.E.A. v6.7.0 pinned, MIT). A provider statically inspects a locally installed reference app and files evidence-backed plan steps.

- **Done:** Cursor composer (10 findings, 10 steps), VS Code change review (11, 10), Perplexity citations (10, 10). All on the Plan tab of the "Aesop Studio design review" project.
- **Blocked:** the owner's strategy document also names **LibreChat** (project continuity, conversation forking) and **NotebookLM / "Gemini Notebook"** (source-centered answers). Neither is installed on this host, so R.E.A. cannot be pointed at them. The only remaining path for those two is Studio's Researcher web route, which uses Firecrawl first and Perplexity second, with Perplexity carrying the citations-and-sources shape most relevant to NotebookLM.

Current state of the Perplexity route: `PERPLEXITY_API_KEY` on the owner's Windows user environment holds the literal placeholder `pplx-your-key-here`. Studio's provider probe correctly reports "Needs key." No calls go out.

## 4. Hard constraints I am operating under

- I may not search the filesystem or environment for credentials. The auto-mode classifier flagged credential exploration earlier in this session; I complied.
- I may not type a credential into any field — including Studio's own kv store, even if the owner typed one into chat.
- I was reminded this turn that I am not the Foreman and do not intake issues on my own. This file is a relay to you, not a Claude-issued work order.

## 5. What I am asking you to decide and own

1. Whether the owner already has a key stored somewhere Codex can see (1Password, your own notes, a prior packet). If so, instruct the owner where to find it, or write it into their environment through a channel I am not authorized to use.
2. If no key exists, authorize the owner to generate one at Perplexity's API console (perplexity.ai → Settings → API), name the minimal plan/tier needed for Studio's bounded usage (`SESSION_CAP=8`, `DAILY_CAP=60`, Firecrawl tried first in `aesop_studio/researcher.py`), and confirm the spend to the owner before they purchase.
3. Confirm the key format Studio expects: `pplx-` prefix, 20+ chars `[A-Za-z0-9_-]` — the redactor pattern committed today in `aesop_studio/security.py` at `aaf564c`.
4. Confirm that neither LibreChat (open source, docs/API available) nor NotebookLM/Gemini Notebook (hosted) qualifies for R.E.A. inspection on this host and that routing them through the Researcher web path is the agreed strategy.

## 6. Reference material for your intake

- Full stress-run report: `docs/foreman-stress-report-20261024.md` on commit `d80594c` (six issues found and fixed, one open ruling request R-1 on dedupe policy).
- Reference-studies feature doc: `docs/study.md`.
- Three completed studies' findings and steps: Plan tab of project `prj_045dca11220a` ("Aesop Studio design review").

## 7. Status at the moment this file is written

- Live Studio on `aaf564c`, PID 58560, 127.0.0.1:8765, serving 200.
- No destructive changes, no external messages sent on the owner's behalf.
- The owner may hand you this file through their own Codex CLI session if the paid-calls gate stays shut.
