# Aesop Studio Browser v2 — Design & Architecture

## 1. Why Browser v1 Fell Short

Browser v1 drove Chrome over the DevTools protocol (`CDP_PORT = 9222`) through a Playwright subprocess (`aesop_studio/browser_worker.py`). That design had four structural flaws:

1. **Painful sign-in (second Chrome identity):** Chrome 136+ blocks `--remote-debugging-port` on the default User Data Directory. To work around that restriction, v1 launched a separate Chrome profile at `%LOCALAPPDATA%\AesopStudio\chrome-studio`. That profile had none of the owner's cookies or sessions, forcing the owner to sign in all over again inside a separate Chrome window (or close and reopen Chrome).
2. **Laggy, indirect UI:** The inspector polled `/api/browser/shot` every 2.5 seconds, encoding and decoding full PNG screenshots over a subprocess pipe, with 500–1200 ms fixed waits on every click, key press, and scroll.
3. **Slow, fragile vision-only agent:** `browse_agent.py` took a screenshot on every step, restricted browsing to three vision routes (`claude`, `codex`, `openai-api`), and asked the model to guess raw `(x, y)` pixel coordinates. It had no structured DOM/accessibility tree, no element refs, no multi-tab control, no in-page search, and no direct citation into the project's research notebook.
4. **Brittle environment coupling:** Fixed port `9222`, mandatory `.venv` Playwright dependency, and broken `.venv` resolution inside linked git worktrees.

---

## 2. Browser v2 Architecture

Browser v2 replaces the single-track CDP screenshot loop with a three-part architecture:

### A. Chrome Extension Bridge in the Owner's Normal Profile (`extension/`)

A Manifest V3 extension (**Aesop Studio Browser Bridge**) runs directly inside the owner's everyday Chrome profile:

- **Zero re-sign-in, zero Chrome restart:** Because the extension runs in the normal Chrome profile, the owner's existing Google, GitHub, and other logins work immediately in place.
- **Origin-locked & owner-confirmed pairing with persistent cryptographic token authentication:**
  - Studio creates a 256-bit `pairing_token` (`secrets.token_urlsafe(32)`) once in its data directory (`browser_pairing.token`, user-only `0600`-equivalent permissions) so normal Studio restarts keep the same token, while `POST /api/browser/pairing/rotate` rotates it on demand.
  - Every extension request to `/api/browser/bridge/*` must present `X-Aesop-Bridge-Token: <pairing_token>`, verified with `hmac.compare_digest`. Unauthenticated localhost callers and cross-origin pages are rejected (`403 Forbidden`).
  - In `extension/background.js`, `AESOP_PAIR` never trusts a page-supplied port: it requires `sender.id === chrome.runtime.id`, requires a loopback `http://127.0.0.1:<port>` or `http://localhost:<port>` origin from `sender.origin` / `sender.tab.url`, and rejects any message whose `port` differs from the sender tab's origin.
  - First pairing, any port change, or any token change requires one explicit owner confirmation click in the extension UI (`"Pair with Aesop Studio at 127.0.0.1:<port>?"` via the extension popup or `chrome.notifications` button), and never silently switches an existing pairing to a different port. While a confirmation is pending, subsequent `AESOP_PAIR` messages are ignored, and pairing requests are rate-limited.
  - Silent re-pairing is permitted **only** when both the sender origin's `port` AND the `token` match the already-confirmed pairing (so restarting Studio on the same port reconnects seamlessly without re-prompting).
- **No credentials or cookies leave Chrome:** The extension never requests `cookies` permission, never reads `document.cookie`, `localStorage`, or `sessionStorage`, and blanks out all password inputs before building DOM snapshots.
- **Dual-transport resilience:** `Browser` (`aesop_studio/browser.py`) prioritizes the Extension Bridge whenever paired and active, while retaining automatic fallback to the Playwright worker (including worktree-aware `.venv` discovery and enhanced DOM snapshot commands in `browser_worker.py`) when running in legacy/CDP environments.

### B. Sub-Second Live Viewport with Direct Input Passthrough & Interactive DOM Overlay

Instead of 2.5-second blind PNG polling:

- **Event-driven frame + DOM push:** The extension captures viewport frames (`chrome.tabs.captureVisibleTab`) and structural DOM/Accessibility snapshots immediately after navigation, DOM mutations, scroll, click, or typing, and pushes them to `/api/browser/bridge/push`. Long-polling on `/api/browser/bridge/poll` dispatches Studio commands to Chrome in `< 50 ms`.
- **Sequence-gated updates (`<= 400 ms`):** Studio's Browser panel polls lightweight state (`/api/browser/state?seq=<n>`) and fetches `/api/browser/shot?seq=<n>` only when `frame_seq` advances, keeping idle bandwidth near zero and interactive latency under `1 s`.
- **Interactive Element Overlay & Direct Input Passthrough:**
  - Hovering over the live viewport highlights interactive elements from the live accessibility/DOM map (`[ref] role "label"`) and dispatches exact semantic element clicks (`click_ref`) or coordinate clicks (`click`) with immediate visual feedback.
  - Wheel scrolling, keyboard typing, a direct **Quick Type / Fill** bar, **Multi-Tab switching** (switch, open, close tabs), **Find in Page**, and a **Reader / Structure** inspector tab work directly inside Studio.

### C. DOM- and Accessibility-Tree-First Semantic Agent (`aesop_studio/browse_agent.py`)

- **Structured Page Snapshot (`snapshot`):** Each step extracts a compact, redacted structural view of the active tab:
  - Page metadata (`url`, `title`, active tab, open `tabs` list);
  - Document outline (`headings` H1–H4);
  - Interactive accessibility/DOM elements (`[#1] link "Releases" -> https://...`, `[#2] button "Latest"`, `[#3] input[search] "Find a release..."`) with stable numeric `ref` IDs, roles, labels, bounding boxes, and safety flags;
  - Structured `forms` summary and clean `main_text` (article/main content).
- **Works Across Usable Chat Routes (Vision Optional):** Because the primary page representation is structured text + accessibility refs, any usable chat route can browse, and steps avoid slow image encoding unless vision fallback is needed and permitted by the project's transfer policy.
- **Rich Semantic Actions & Notebook Citation:**
  - `navigate` (`url`)
  - `click_ref` (`ref`) and `fill_ref` (`ref`, `text`, `submit`) for deterministic DOM interaction without coordinate guessing
  - `click` (`x`, `y`), `type` (`text`), `key` (`key`), `scroll` (`dy` / `direction`)
  - `find` (`query`) for instant in-page text and element search
  - `switch_tab` (`tab_id`) and `new_tab` (`url`) for multi-tab workflows
  - `cite_notebook` (`title`, `claim`, `locator`, `limitation`) and `done` (with optional `cite` / `findings`) to record the page as a source and save cited findings directly into the project's Research Notebook.

---

## 3. Defense-in-Depth Safety Guarantees

1. **Loopback-Only + Origin-Locked, Owner-Confirmed Pairing Token:** Server binds `127.0.0.1` only. All `/api/browser/bridge/*` routes require `X-Aesop-Bridge-Token` matching the persistent `Browser.pairing_token` (`browser_pairing.token` in the data directory, user-only permissions) via `hmac.compare_digest`. The extension derives the port strictly from `sender.origin` / `sender.tab.url` (`sender.id === chrome.runtime.id`), requires explicit owner confirmation in the extension UI (`"Pair with Aesop Studio at 127.0.0.1:<port>?"`) on first pairing or any port/token change, ignores `AESOP_PAIR` while a confirmation is pending, and rate-limits pairing requests.
2. **Hard Refusals on Passwords, CAPTCHAs, and Purchases:** Enforced in `browse_agent.py`, `browser.py`, `browser_worker.py`, and `extension/content.js`:
   - Agents cannot type into or fill password fields (`input[type=password]`, `autocomplete=current-password|new-password`, or password-labelled inputs).
   - Agents cannot interact with CAPTCHA challenges (`recaptcha`, `hcaptcha`, `cf-turnstile`, `captcha`).
   - Agents cannot click purchase/checkout confirmation triggers (`buy now`, `place order`, `complete purchase`, `pay now`, `confirm payment`) or type into payment card fields (`cc-number`, `cc-csc`, `cvv`).
3. **Visible & Stoppable:** Every agent step is recorded with its thought, action, target detail, and page URL/title, and the owner's **Stop** button halts the loop and cancels any running provider turn immediately.
4. **Zero Credential Leakage:** URLs pass through `security.sanitize_url()` and all extracted text, labels, thoughts, and answers pass through `security.redact()`.

---

## 4. Transport (push frames on data lane, separate HTTP lanes)

Studio’s stdlib `ThreadingHTTPServer` handles **one request at a time per HTTP/1.1 connection**. When the extension **pushed** full PNGs on the same keep-alive connection as long-poll command fetches, a command could sit behind a ~35 KB push for hundreds of milliseconds and then miss the next poll window (~1 s), producing ~1.5 s action ack latency even though the server and bridge logic were fast.

**Data-lane frame push (de-duplicated):** The extension keeps `latestFrame = { seq, png }` in the service worker. After each successful `captureVisibleTab`, it bumps `frame_seq` and stores the PNG locally. **Routine pushes** on `?lane=data` carry DOM snapshot, tabs, and `frame_seq`; they include a **`png` field only when `frame_seq` advanced since the last push** (at most one PNG per new capture—never a repeated PNG for the same seq). Studio’s `bridge_push` ingests that PNG into `last_png` and advances `frame_seq`. **`shot(full=False)`** serves the cached `last_png` and does **not** poll for `{ op: "frame" }`. **`shot(full=True)`** still uses `{ op: "frame" }` on the command poll path to pull the latest cached PNG on demand.

**Why a push could carry a new `frame_seq` and no `png` (repair 7):** The loop stored `{ seq, png }` on the single shared `latestFrame`, then `await`ed `listBrowseableTabs()` before `buildPushPayload` copied `png`. That helper attached `png` only when the shared property was still non-empty. `lastPushedFrameSeq` does not move until a png is actually sent, and `resetCaptureState` (the only writer of an empty png) was not on the poll, re-pair, or activation paths — it would also have zeroed `seq`, which the live probe did not show. There is no second `latestFrame` binding. The capture string itself was not what got serialized: after the yield, the payload re-read the shared object, so a new `frame_seq` went out with no `png` key whenever that property was empty (a second loop could start too, because `frameLoopPromise` was assigned only once the async body reached its first `await`). The push now takes the captured png in a local `const`, builds the body from that const, and advances `lastPushedFrameSeq` from it only after the post succeeds. A poll that fails with a network error for more than 5 seconds calls `resetCaptureState()` on the next success and re-pushes, so a new Studio process on the same port and token does not keep a stale sequence.

**Tab visibility:** `captureVisibleTab` only captures the **active tab of the focused window**. If the driven tab is in the background of its window (for example Studio is front-most in the same window), Chrome returns an empty string; the extension sets `captureError` (“bring the Chrome tab to front”), activates the target tab **within that window only** (never another window), and retries on the next capture kick. Keep the automated site in a **separate Chrome window** from Studio when possible.

**Separate lanes:** Every `studioFetch` uses `keepalive: false` and `cache: "no-store"`, with `?lane=poll` on `/api/browser/bridge/poll` and `?lane=data` on push/reply (the server ignores the marker; it exists so the browser does not reuse one TCP connection for poll and data). That way a held push on the data lane cannot block command polling.
