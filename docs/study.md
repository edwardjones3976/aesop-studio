# Reference studies (R.E.A.)

A reference study lets a provider inspect a *reference application* you already have installed (Cursor, VS Code,
Perplexity desktop, …) and report, with evidence, how it implements something Studio wants to do better. The
findings go to the project's notebook (private source + findings) and the suggested steps go to the Plan tab as
`Study: <app>` items, where the ordinary build + review flow picks them up.

The inspection is done with [R.E.A.](https://github.com/morluto/rea) (MIT, "Reverse Engineer Anything"), a local MCP
server pinned to version `6.7.0`. Static JavaScript/Electron inspection needs no native engine.

## What is and is not allowed

- Only folders you registered in Studio (Plan tab → *Study a reference*). The registry refuses credential folders,
  the Windows folder, your home folder and drive roots, exactly like project roots.
- Static inspection only. The reference app is never executed; the provider runs with a read-only sandbox, no shell,
  no edit tools, and only file reads plus the `rea` MCP tools.
- The study's working folder is Studio's own `studies/<id>/` directory. The project folder and the reference folder
  are never written to. A study never counts as the project's build writer.
- One acknowledgement, once: the study's report (file names, module structure, observed behaviour) leaves this PC to
  the provider you pick, which may use cloud inference.
- Learn behaviour and architecture; copy nothing. The prompt forbids reproducing the target's code, strings or assets.

## How to run one

1. Plan tab → **Study a reference**. Pick a registered app, or register one (well-known local apps are offered).
2. Say what to study, e.g. *chat composer: drafts, attachments, retry and edit*.
3. Pick Claude Code or Codex. Codex gets `-c mcp_servers.rea…`; Claude Code gets `--mcp-config` with Studio's own
   `mcp.json`, so the study works even if the global R.E.A. registration drifts.
4. The study runs for up to 20 minutes. The Plan tab shows it under *Reference studies* with claim / evidence /
   limitation rows and the full report; new steps appear on the plan tagged `Study: <app>`.

From chat: `/study <topic>` opens the same dialog. In a roundtable or War Room, a speaker or you can ask the
Researcher with `RESEARCH: study <App> <topic>`; the result joins the timeline as evidence.

## Pilot batch

| Studio weak spot | Reference | Topic |
|---|---|---|
| Chat composer, paste/attachments, retry/edit | Cursor | composer and message actions |
| Agent checklist / Plan tab dynamics | Cursor | agent task panel and progress stream |
| Command palette, inspector layout | VS Code / Antigravity | workbench layout, palette, panel persistence |
| Research answers, citations, follow-ups | Perplexity desktop | answer rendering and citation UI |
| Provider switching mid-chat | Cursor | model switch and context carry-over |

## One-time setup (owner)

```
npx -y rea-agents@6.7.0 setup --client claude_code --client codex
npx -y rea-agents@6.7.0 doctor --client claude_code --json
```

A preserved copy of the repository, its bundle (with SHA-256) and the npm package live in
`%USERPROFILE%\Documents\REA-Archive`.
