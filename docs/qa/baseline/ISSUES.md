# Baseline UI: observed issues (commit 6223fc8, before the Coal/Ember redesign)

These screenshots were captured with `tools/ui_qa.py --label baseline` against the committed app, using synthetic seeded data and the SIMULATED route. They show the implemented app, not a reference mock.

| # | Observed | Where | Evidence |
|---|---|---|---|
| B1 | Page scrolls sideways at 360px on every captured view (scrollWidth 388 > 360). Long root path and tab row don't wrap. | 360×780 chat/agent/research/evidence | `results.json`, `360x780-*.png` |
| B2 | At phone width the sidebar stacks above the project, pushing the workspace below the fold. There's no bottom navigation. | 390/360 | `390x844-chat.png`, `360x780-chat.png` |
| B3 | Desktop canvas is mostly empty. There's no inspector, the conversation list and empty-state text are misaligned, and hierarchy is weak. | 1440×900, 1920×1080 chat | `1440x900-chat.png` |
| B4 | The provider control shows the route id only ("— choose —"). It doesn't name the access route (official CLI / billed API / handoff). | all | header |
| B5 | No command palette, no keyboard shortcuts beyond Ctrl+Enter and tab arrows, no breadcrumb. | all | n/a |
| B6 | Browser requests `/favicon.ico` and gets a 404 (console error on every load). | all | `results.json` page_errors |
| B7 | Light-only warm palette. Dark mode follows the OS but isn't designed. | all | screenshots |
