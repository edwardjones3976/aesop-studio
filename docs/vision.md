# Aesop Studio: vision charter and decision record

## Vision charter

**One dependable personal workspace.** Every feature serves one journey: open a project → choose its provider → attach a file → converse or run an agent → inspect the result → save it → close → resume.

Quality bar:
- **Coal / Ember UI (owner contract, 2026-10-23).** Desktop-first layout: topbar, navigation rail, project explorer, conversation canvas and inspector (Preview / Files / Changes / Terminal / Logs, each backed by real data or a truthful empty state). Dark tokens #0B111A / #141F2C / #243243, coral #FF916C for the single primary action, mint #80E1CB for verified state, focus #9BD7FF. Ctrl+K palette, Ctrl+1/2/3, Ctrl+Enter, Escape with focus restore. Exact breakpoints at 1600 / 1280 / 1024 / 768 px, with bottom navigation at ≤767px. Verification is in `docs/qa/after/README.md`.
- **Honest states.** Saved, submitted, generated, failed and handed off are visibly different. Studio shows no fake typing, fabricated progress, or synced history it cannot see.
- **Calm, readable UI.** System fonts, strong hierarchy, visible focus, and full keyboard operation. There is no decorative dashboard clutter. (The original warm light palette was replaced by the Coal / Ember contract above.)
- **Owner stays in control.** There is one folder per project and one writer per project. Studio never switches providers without asking, never sends a file without a transfer grant, and never deletes originals.
- **Evidence over claims.** Dashboards show only recorded runs. Empty means empty.

Out of scope: music, image or video generation, media editing, model training, public hosting, and placeholder workspaces.

## Foundation decision

| Option | Fit | Why not / why |
|---|---|---|
| LibreChat | Multi-provider chat over **API keys**; MongoDB + Docker-first | Would put every route on metered APIs, which the $0 non-OpenAI rule forbids. Heavy footprint, and it doesn't supervise official CLIs. |
| Open WebUI | Polished chat UI, Ollama/OpenAI-compatible endpoints | Large Python + Svelte stack, a branding clause in recent licenses, and no support for supervising official agent CLIs. |
| Libre WebUI | Lighter, Ollama-centric | Same gap: built around model endpoints, not subscription-signed agent CLIs. |
| **Thin custom shell (chosen)** | Python stdlib server + SQLite + vanilla JS | **Justified:** the only $0 routes available are the official `codex` and `claude` CLIs signed in through subscriptions. Every listed foundation would need adapters for these anyway, and none of them provide task supervision, a ledger, or reconciliation. The stdlib-only build means no dependencies, no install, and nothing to patch. |

Expected footprint: about 1,600 lines of Python, about 450 lines of JS/CSS/HTML, and one SQLite file.

## Workforce

- Director/orchestrator: this session (Claude Code; Codex was the named Director but the owner submitted the mission here). It covered audit, architecture, implementation, and live verification.
- Subordinate session 1: implemented the frontend package (`static/` only, one writer). Its first pass followed an open-ended visual brief; it was then redirected to the owner's Coal/Ember contract. QA defects went back to it and it fixed them. The Director made three small integration fixes in `static/` afterwards: control heights, cost precision, and CLI-log streaming. The last of these was a flaw in the Director's own brief.
- Subordinate session 2: an independent, non-contributing security and acceptance reviewer.

## Spend

- **OpenAI (the only authorized biller): $0.000126.** Three bounded `gpt-6-luna` integration calls, each reserved at $0.0012 before sending and settled from the API's reported usage.
- CLI routes run on existing plan quota and are recorded as `subscription_included` ($0).
- The mission permit is forced off at every server start and was off at completion.
- **Non-OpenAI:** one Firecrawl search (2 Firecrawl credits) was used early for pricing research. Whether those credits are free on the owner's plan is unverified, so further research used Studio's own fetcher.
- The budget was not spent for its own sake. Design work needs no paid calls, and padding spend is prohibited.
