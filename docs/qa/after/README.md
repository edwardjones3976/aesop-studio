# Coal / Ember UI: verification record (AC11)

All screenshots here are of the **implemented app**, served by a throwaway local server with synthetic data. None are reference mocks. Pre-redesign screenshots and the issues observed in them are in `../baseline/` (`ISSUES.md`).

## Viewports (`tools/ui_qa.py --label after`)

| Check | Result |
|---|---|
| Target viewports 1920×1080, 1440×900, 1366×768, 1024×768, 768×1024, 390×844, 360×780 | 7 × 7 views = **49 screenshots** |
| Page-level horizontal overflow | **0 of 49** (baseline: overflow on every view at 360px) |
| Page errors / console errors | **0** (baseline favicon 404 fixed) |

## Keyboard, focus, zoom, motion (`tools/ui_a11y.py` → `a11y.json`)

| Check | Result |
|---|---|
| Ctrl+K palette | Opens with focus inside, filters ("evid" → *Open Evidence*), Escape closes, **focus restored** to the trigger |
| Ctrl+1 / 2 / 3 | Chat / Build / Research switch; **ignored while typing** in a textarea |
| Composer | 98px minimum, grows to a **240px** cap at 60 lines |
| Visible focus | Every tab stop shows a ring. Resize handles show a focus-coloured bar (pseudo-element); the composer textarea shows a ring on its container (`:focus-within`). |
| Accessible names | 0 unnamed controls |
| Control height ≥ 40px on desktop | 3 chips were 32–36px; fixed to 40px and re-verified (0 under 40px) |
| Resizable panes | 2 `role=separator` handles; arrow keys change the width (220 → 196) and it **persists across reload** |
| 200% zoom (960×540 and 683×384 CSS viewports) | No overflow on chat/build/research |
| `prefers-reduced-motion` | Longest transition 1ms |
| Token contrast (computed) | Text on canvas/panel/raised from 5.9:1 to 17.1:1; coral buttons use dark text (8.6:1); white on coral (2.2:1) is not used |

## Real journey (`tools/ui_journey.py` → `../journey/`)

This ran against the owner's running Studio with live providers. Every step is driven through the UI:

1. Create the project in the dialog, set file-transfer permission in Settings, upload in the inspector's Files tab, select the attachment chip, then Ctrl+Enter.
2. **codex (official CLI · plan quota)** answered correctly: **9.14s provider wait, 9.44s end to end**. The answer was saved as an artifact.
3. The **mission permit was switched on in the UI**, the provider changed to **openai-api (separately billed API)**, and the answer streamed. Cost line `gpt-6-luna · 126→70 tok`: **1.69s provider wait, 3.36s end to end**. The permit was switched off again in the UI.
4. **Server restart**, then sign in with the new one-time link. The conversation, both answers, the cost line and the saved artifact were all present.

## Defects found and fixed during this verification

| Defect | Fix |
|---|---|
| The pending CLI chat message streamed the raw CLI log (prompt echo including attached file text, session id, config warnings) as "partial text". This caused a **false-positive** 2.2s timing in the first journey run. | `stream_is_answer` flag: only API routes stream answer text. CLI logs stay in the Terminal tab. The journey now waits on API message state, not page text. |
| Chat requests appeared in the Build task list | `/api/projects/<id>/tasks` returns agent-mode tasks only (+ regression test) |
| Global views showed the project header; duplicate "saved" pills; provider name shown twice | Fixed by the UI author |
| Sub-cent costs rendered as `$0.0000` / `$0.00` | Costs under one cent show 6 decimals |

## Not verified / known gaps

- Screen-reader output itself (NVDA/Narrator) was not exercised. Only semantics (roles, names, live region) were checked.
- Real touch devices were not used. Touch sizing comes from `(pointer: coarse)` CSS, checked by inspection only.
- There is no light theme (optional in the contract).
- Contrast for semi-transparent overlays and chips was checked visually, not computed.
