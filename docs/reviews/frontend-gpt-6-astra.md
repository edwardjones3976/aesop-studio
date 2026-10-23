# Paid frontend review (gpt-6-astra)

_Codex API, 2026-10-23 03:10; 36702 input / 4911 output tokens; cost $0.61257; status completed; 116.8s. Findings are model output to be verified, not facts._

## Summary

**The supplied `app.js` contains a syntax error that prevents the entire application from starting.** The remaining findings are latent issues identified by inspection; they become relevant once that blocker is fixed.

Only the supplied JavaScript and HTML were reviewed. Backend validation, idempotency, CSP, and CSS behavior cannot be verified here.

## Startup and navigation

### 1. High — Syntax error prevents all JavaScript execution
**Location:** `static/app.js:1136`

- **Failure scenario:** The line ends with `})); }));`. The first sequence closes the `groups.map(...)` callback and `replaceChildren(...)`; the second is extraneous. The script fails to parse, so even `boot()` never runs.
- **Minimal fix:** Remove the final extra `}));`. Add a syntax check such as `node --check static/app.js` to validation.

### 2. High — Project requests can overwrite a newer project selection
**Location:** `static/app.js:716–724`, `661`, `713`

- **Failure scenario:** Open project A, then B. If A’s GET finishes last, it assigns A to `S.project` and changes the workspace back. Similarly, a pending provider/settings PATCH for A can assign its response to `S.project` after the user has opened B.
- **Minimal fix:** Capture the project ID and a navigation generation. Check both before applying responses or executing follow-up navigation. PATCH responses should update the active project only if its ID still matches.

### 3. High — Late renders replace the currently selected view
**Location:** `static/app.js:753–761`, `888–936`, `1020–1049`, `1080–1108`, `1112–1144`, `1189–1231`

- **Failure scenario:** Open Research on a slow connection, then switch to Build. Research’s requests finish later and replace `#view`, while the navigation still says Build. Chat’s generation only changes when another chat render starts, so leaving Chat does not invalidate it. Mutation callbacks such as `renderResearch()` after fetching a source can also pull the user back into an old view.
- **Minimal fix:** Use a shared workspace-render generation, incremented on every navigation. Capture project/tab/global-view identity and verify it before state changes and DOM replacement. Apply the same checks to post-mutation refreshes.

### 4. High — A stale chat render mutates the new conversation state before checking its generation
**Location:** `static/app.js:891–896`

- **Failure scenario:** Project A’s conversation request is pending when the user opens B. A’s response can set `S.conv` to an A conversation and reset stream state before reaching the generation check. B’s renderer then sees a non-null conversation and can issue B-project requests using A’s conversation ID.
- **Minimal fix:** Check render generation and project identity immediately after each `await`, before touching shared state. Keep conversation selection local until the render is confirmed current.

### 5. High — Existing chat controls use the newly selected conversation ID
**Location:** `static/app.js:900`, `914`, `919`, `976`

- **Failure scenario:** While viewing conversation A, click B. `S.conv` changes immediately, but A’s composer remains visible while B loads. Pressing Send or Preview during that interval submits A’s visible draft against B’s ID. Old polling callbacks also read the mutable ID.
- **Minimal fix:** Capture a `cid` for each rendered conversation and use it in all URLs. Disable or detach the outgoing composer when switching conversations.

### 6. Medium — Changing the default provider leaves execution information stale
**Location:** `static/app.js:661`, `910–934`, `1030–1046`

- **Failure scenario:** Change the provider in the header while Chat or Build is open. Only the header is rerendered. The composer’s provider/billing badge and Build’s CLI description still name the previous provider.
- **Minimal fix:** Update provider-dependent portions of the active view after the PATCH succeeds, preserving draft input. Ensure the displayed execution route agrees with the route the request will use.

## Submission and error handling

### 7. High — Execution controls permit concurrent duplicate submissions
**Location:** `static/app.js:911–934`, `1024–1029`, `611–621`

- **Failure scenario:** Double-click Send, Start task, or Run manual comparison, or repeatedly press Ctrl+Enter. There is no in-flight lock, so multiple POSTs are issued. These can produce duplicate messages or executions unless the backend deduplicates them; backend behavior is not shown.
- **Minimal fix:** Add per-operation busy state, disable the relevant controls, and guard keyboard submission too. Use backend idempotency keys for execution requests.

### 8. Medium — Sending a message can erase text typed while the request is pending
**Location:** `static/app.js:912–915`

- **Failure scenario:** Send “First message,” then type the next message before the POST completes. The success handler unconditionally sets `ta.value = ""`, deleting the new text.
- **Minimal fix:** Clear the submitted draft immediately and restore it on failure, or clear on success only if the textarea’s value/revision still matches the submitted draft.

### 9. Medium — Read failures leave the app partially initialized or showing the previous view
**Location:** `static/app.js:657–658`, `760`, `891–895`, `1016`, `1022`, `1082–1083`, `1114`, `1142`, `1273`

- **Failure scenario:** `/api/routes` fails during boot: initialization stops before navigation handlers are installed, without a visible error. A failed workspace GET similarly produces an unhandled rejection because `setTab()` neither awaits nor catches its renderer.
- **Minimal fix:** Catch initialization failures and show a retryable error. Route all asynchronous renders through an awaited error boundary that only displays errors for the still-active view.

### 10. Medium — One message-refresh failure permanently stops chat polling
**Location:** `static/app.js:975–989`, `1011–1012`, `1016`

- **Failure scenario:** While an answer is pending, the timer clears itself and awaits `drawMsgs()`. If the messages GET fails, execution exits before installing another interval. The answer remains “submitted” until the user manually rerenders the conversation.
- **Minimal fix:** Use a polling loop that reschedules in `finally`, with backoff and an active-view check. Show a reconnecting/error state instead of silently freezing.

### 11. Medium — Automatic refreshes destroy unrelated unsaved drafts
**Location:** `static/app.js:815–821`, `908`, `1087–1089`, `1099–1102`

- **Failure scenario:** Type a chat draft, then upload a file through the inspector. Upload completion calls `renderChat()`, replacing the composer with an empty textarea and clearing attachment selection. Likewise, fetching a Research source destroys a finding being composed in the adjacent card.
- **Minimal fix:** Store drafts and attachment selections outside the rendered DOM, or refresh only the affected file/source list.

## Roundtable state

### 12. High — Roundtable responses can modify a different modal session or draft
**Location:** `static/app.js:405–418`, `583–600`, `611–638`

- **Failure scenario:** Open a roundtable, close it while loading, then reopen it. The old response passes `if (!RT)` because a new `RT` exists and populates the new session. Within one session, start comparison for draft A and open B before it finishes: line 618 writes A’s results into the current `RT.rec`, which may now be B.
- **Minimal fix:** Capture the exact session object and operation/draft generation. After every await, require `RT === capturedSession` and the expected draft/operation identity before committing results.

### 13. Medium — Export silently ignores edits to an already-saved draft
**Location:** `static/app.js:605–609`

- **Failure scenario:** Save a draft, edit its objective, roster, or caps, then click Export planning packet. Because `RT.rec` already exists, export skips saving and downloads the older server record.
- **Minimal fix:** Save the current form successfully before exporting, or disable export while dirty and explicitly offer “Export last saved version.”

### 14. Medium — Preflight results remain presented as current after edits
**Location:** `static/app.js:437–446`, `486–491`, `512`, `542–558`

- **Failure scenario:** Run preflight, then change the objective, roster, mode, or caps. `RT.pre` is not invalidated, so the sidebar continues showing pass/fail results for the previous configuration.
- **Minimal fix:** Mark preflight stale on every relevant edit. Hide or clearly label stale results until preflight is rerun against the current draft revision.

## Task watching and focus

### 15. Medium — Task-ID checks do not prevent stale responses after A → B → A selection
**Location:** `static/app.js:766–779`

- **Failure scenario:** Select task A, then B, then A again before A’s first request finishes. Both A requests pass `tid === W.tid`. Their output can be appended twice, offsets can be overwritten out of order, and both requests can schedule polling timers.
- **Minimal fix:** Give every watcher start a generation token, even when returning to the same task ID. Validate that token before applying output or scheduling another tick; abort superseded requests where possible.

### 16. Medium — Permanent task-fetch failures retry forever without explanation
**Location:** `static/app.js:779`, `866`

- **Failure scenario:** A watched task starts returning 404 or authorization failures. The watcher retries every four seconds indefinitely, while the UI remains stale or says “Loading task record…”.
- **Minimal fix:** Stop on permanent failures, expose the error and a Retry action, and reserve bounded/backoff retries for transient errors.

### 17. Medium — Polling repeatedly removes the keyboard-focused task action
**Location:** `static/app.js:777`, `1060–1075`

- **Failure scenario:** Keyboard-focus Cancel or View output on a running task. Each watcher update rebuilds `head` and `info`, removing the focused button approximately every 1.5 seconds. Focus is lost, making the task actions difficult to use.
- **Minimal fix:** Keep action controls stable and update only state/text nodes. If replacement is unavoidable, restore focus to the equivalent surviving control.

### 18. Low — Task hooks retain detached view trees
**Location:** `static/app.js:766`, `781`, `1075`

- **Failure scenario:** Select a Build task, then leave the view or switch projects. `W.hooks.build` continues referencing its detached detail element because neither navigation nor `stopWatch()` removes the hook. It remains retained until another task detail replaces it.
- **Minimal fix:** Unregister the Build hook when its view unmounts and clear obsolete hooks during watcher teardown. This is bounded retention, not evidence of an endlessly growing leak.

## Dialogs and accessibility

### 19. Medium — Command palette can replace an already-open dialog’s operation
**Location:** `static/app.js:129–145`, `279–282`, `317–320`, `329–347`

- **Failure scenario:** Open Project settings, press Ctrl+K, and choose New project. The shortcut is processed before the “dialog open” guard. The second `dialog()` call replaces the shared form and `onclose` handler, abandoning the original promise and its settings operation.
- **Minimal fix:** Do not open the palette while another modal is active, or explicitly close/cancel and settle the existing modal before starting another action. Prevent concurrent use of the shared dialog helper.

### 20. Medium — Generic dialogs have no accessible name
**Location:** `static/index.html:93`; `static/app.js:132`

- **Failure scenario:** A screen-reader user opens Settings, Archive confirmation, or Context preview. The dialog contains a visible heading but has neither `aria-label` nor `aria-labelledby`; the heading does not automatically name the dialog.
- **Minimal fix:** Give the generated heading a stable ID and set `aria-labelledby` on `#dlg`.

### 21. Low — Lane filters advertise radio semantics without radio keyboard behavior
**Location:** `static/app.js:425–426`

- **Failure scenario:** A keyboard/screen-reader user encounters the “Filter lanes” radiogroup and tries arrow keys to change selection. No arrow-key handling exists, and every radio-like button remains a separate Tab stop.
- **Minimal fix:** Use native radio inputs, or implement roving tabindex and arrow-key selection. Alternatively, expose these as ordinary toggle buttons rather than radios.

## Security caveat

### 22. Medium — Evidence links accept unvalidated URL schemes
**Location:** `static/app.js:1267`

- **Failure scenario:** An evidence record containing a non-HTTP URL is assigned directly to an anchor’s `href`. Text-node rendering does not sanitize URL attributes, and `noopener noreferrer` is not a scheme allowlist.
- **Minimal fix:** Parse the URL and allow only intended schemes, normally `https:` and `http:`; render rejected values as plain text.
- **Uncertainty:** This is a concrete unvalidated URL sink, **not a confirmed exploitable XSS path** from the supplied material. Backend control of `r.url`, CSP, and browser handling of scripted URLs in new tabs are not shown.
