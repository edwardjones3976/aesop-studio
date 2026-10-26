# Work order — Studio browser v2 (challenge: Antigravity → Grok → Cursor → Codex)

**Issued by:** Claude, Foreman (BlackBox), 2026-10-26
**Owner's instruction:** "Ask Antigravity to build a better version of the browser in Studio, your version isn't up to par and it's too difficult to sign in on there. See if they can make a different version… Attempt to improve it first, or start it from scratch if it can't be corrected. If Antigravity can't make a better version, challenge Grok, Cursor, then Codex, in that order, until we have a perfectly smart and useful browser in Aesop Studio."
**Writer, round 1:** Antigravity. Later rounds, if needed: Grok, then Cursor, then Codex. Each challenger gets this file plus the previous round's evaluation.
**Workspace:** a linked git worktree of `C:\Users\edwar\Claude\Projects\Aesop-Studio` on branch `browser-v2/<provider>`, created from `main`. Work only there; never on `main` and never in the owner's live data folder.

## Do something different from the current version

The current browser was built by Claude across six commits: `f2fd9bb`, `93f0346`, `13f04b0`, `34b732d`, `6a3fd87`, `9007921`. The owner judges it not good enough. **Don't repeat its design.** Improve it if its core can be saved; otherwise replace it.

### How it works today

- `aesop_studio/browser.py` (Studio side). It manages one Chrome driven over the DevTools port, `CDP_PORT=9222`. Chrome 136+ refuses DevTools on the default profile, so Studio launches a **second Chrome profile** at `%LOCALAPPDATA%\AesopStudio\chrome-studio`. The Desktop shortcut "Chrome - Aesop Studio" uses the same flags. connect() may ask to close and reopen Chrome.
- `aesop_studio/browser_worker.py`. A subprocess under the project `.venv` Python with Playwright. One request, one reply, serialized, 45 s command timeout.
- `aesop_studio/browse_agent.py`. "Let \<provider\> browse": screenshot → vision provider proposes one JSON action → run it, repeated. Vision routes are `claude`, `codex` and `openai-api`; at most 15 steps. It refuses to type into password fields and solves no CAPTCHAs.
- Server routes in `aesop_studio/server.py`: `/api/browser` plus `navigate`, `act`, `shot`, `text`, `links`, `drive`, `drive/stop`, `connect`, `stop`, and `/api/projects/<id>/browser/attach`.
- UI: the browser panel in the right-hand inspector, inside `static/app.js` (about 266 KB) and `static/app.css`. The panel shows **screenshots**; it is not a live page.

### What's wrong (owner's complaints, plus observed problems)

1. **Sign-in is too hard.** The second profile has none of the owner's logins, so they must sign in again inside a special Chrome window. Chrome sometimes has to be closed and reopened. Two Chrome identities are confusing.
2. **Not live.** Screenshot polling feels laggy and indirect. You can't simply click, type and scroll the page as in a real browser.
3. **Not smart enough.** Providers see mostly screenshots. Page understanding (text, DOM, links, forms, tabs) is thin, and the step-by-step vision loop is slow.
4. **Fragile setup.** Port 9222 is fixed, Playwright depends on the `.venv`, and there are launcher-stub process issues.

### Directions worth considering (your call; justify it)

- **A Chrome extension bridge in the owner's normal profile.** The extension talks to Studio over loopback (or native messaging). No DevTools port and no second profile, so all existing logins just work. The extension can read the DOM and text, take tab captures and act on the page with the owner's consent.
- **An embedded live view.** A WebView2 shell, or a live streamed tab (for example a CDP screencast) with real input passthrough instead of still screenshots.
- **A smarter agent.** DOM- and accessibility-tree-first actions, with screenshots only as fallback. Multi-tab support, find-in-page, a reading mode, summarize and cite the page into the project notebook, and a history of what the agent did.
- Anything better. Document why it beats the current design.

## Acceptance (the Foreman tests each one live)

1. **Sign-in:** the owner's existing Google/GitHub logins work without signing in again, and without closing or reopening their Chrome. If a one-time step is unavoidable, it takes at most one click and is explained in the UI.
2. **Live and direct:** the owner can navigate, click, type and scroll from Studio with page updates that feel live (≤ 1 s).
3. **Smart:** a provider can read the page structurally (text, links, forms) and finish a 5-step goal ("open the GitHub repo X, find the latest release, summarize it into the notebook") more reliably and faster than the current version.
4. **Safety stays:** loopback only. Agents never type into password fields, solve no CAPTCHAs and make no purchases. Every agent action is visible and has a Stop button. No credential is ever read into Studio or written into logs (`security.redact` covers the key shapes).
5. **Engineering:**
   - Windows 11, and Chrome current stable.
   - The Studio server stays Python stdlib-only. Helpers may use the `.venv`, and a browser extension may be plain JS.
   - Tests are added; the existing suite passes (`scripts\run_tests.ps1`, offline, simulated routes).
   - README "Browser" docs are updated.
   - Changes stay within the browser surface: `aesop_studio/browser*.py`, `browse_agent.py`, the browser routes in `server.py`, browser UI in `static/`, any new `extension/` folder, tests and docs.
6. **Hand-in:** commit on your branch with a summary of the design decision and what is different from v1. Don't merge. The Foreman evaluates, then independent review goes to the Warden (Cursor) unless Cursor wrote that round, in which case Codex reviews.

## Evaluation and escalation

- The Foreman scores each round against Acceptance 1–5 with live evidence. A pass on all five means done.
- Any failing item: the next challenger gets this file, the previous branch and the scorecard, and may build on it or start over.
- Order: Antigravity → Grok → Cursor → Codex.

## Round log

- Round 1, Antigravity: dispatched 2026-10-26 (see the Foreman report).
