# Aesop Studio: vision charter and decision record

## Vision charter

**One dependable personal workspace.** Every feature serves one journey: open a project → choose its provider → attach a file → converse or run an agent → inspect the result → save it → close → resume.

Quality bar:
- **Honest states.** Saved, submitted, generated, failed and handed off are visibly different. Studio shows no fake typing, fabricated progress, or synced history it cannot see.
- **Calm, readable UI.** A warm neutral palette with system fonts, one accent colour, and full light and dark modes. Focus rings are visible, tabs work from the keyboard, and the layout reflows at phone width. There is no decorative dashboard clutter.
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
- Subordinate session 1: not used. The implementation was small enough to keep a single writer.
- Subordinate session 2: an independent, non-contributing security and acceptance reviewer.

## Spend

$0 incremental. Both live routes run on existing plan quota, and no OpenAI API calls were made. The ledger records each run as `subscription_included`. The billable permit is forced off at every server start.
