# Paid visual review (gpt-6-astra)

_Codex API, 2026-10-23 03:10; 11335 input / 3266 output tokens; cost $0.27665; status completed; 63.4s. Findings are model output to be verified, not facts._

## Prioritized findings

Screenshot references are used because source files weren’t supplied. CSS selectors below are illustrative. Findings describe visible states—not unverified scrolling, hover, or interaction behavior.

### 1. **High — Selected provider and send-route indicator disagree**
**Location:** `journey/4-api-answer-cost.png` — provider selector, topbar, composer footer.

- **Failure scenario:** The selector and topbar show **openai-api / separately billed API**, but the composer says **codex / official CLI · plan quota**. A user cannot tell whether the next Send incurs API charges.
- **Minimal fix:** Bind all three indicators to the same effective next-send route. This requires a state fix, not CSS alone. Keep the billing scope adjacent to Send with `.send-route { display:flex; flex-wrap:wrap; gap:4px 8px; }`. The screenshot does not establish which indicator is wrong.

### 2. **High — Two projects become visually indistinguishable**
**Location:** `journey/4-api-answer-cost.png` — first two project-explorer rows.

- **Failure scenario:** Both names truncate to nearly identical “Live journey (QA, sy…” labels, both avatars say “LJ,” and both paths share the same visible prefix. A user switching projects cannot reliably distinguish the destinations.
- **Minimal fix:** Allow two-line names and display the distinguishing folder suffix rather than the shared path prefix:
  ```css
  .project-name { white-space:normal; overflow-wrap:anywhere; }
  .project-row { align-items:flex-start; }
  ```
  Use an explicit short project identifier if the names still collide.

### 3. **High — Research form fields have no persistent individual labels**
**Location:** `after/768x1024-research.png` — “Add a source” and “Record a finding.”

- **Failure scenario:** Once text is entered, placeholder-only cues such as “Locator: section, page, line or quote” and “Limitation (optional)” disappear. Users reviewing a populated finding lose the visible explanation of each field.
- **Minimal fix:** Add visible `<label>` elements for URL, claim, source, locator, and limitation:
  ```css
  .field { display:grid; gap:6px; }
  .field label { font-size:12px; font-weight:600; }
  ```
  Accessible names cannot be assessed from the screenshot.

### 4. **Medium — Mobile response metadata overwhelms the answer**
**Location:** `after/390x844-chat.png` — assistant message.

- **Failure scenario:** Provider badges, timing, and Save consume three rows before the two-line response begins. Scanning the answer requires looking past substantially more metadata than content.
- **Minimal fix:** Put provider and Save on one compact row; move timing beneath the answer:
  ```css
  .message-header { display:flex; align-items:center; gap:8px; }
  .message-save { margin-left:auto; }
  @media (max-width:600px) {
    .message-header { flex-wrap:wrap; }
    .message-timing { font-size:12px; }
  }
  ```
  Move the timing element in the markup rather than relying on visual order alone.

### 5. **Medium — Desktop keyboard hints occupy scarce mobile space**
**Location:** `after/390x844-chat.png` — composer; `after/360x780-agent.png` — task footer.

- **Failure scenario:** “Ctrl Enter” remains prominent on phone layouts. In Chat, it takes an entire additional footer row and pushes the primary action farther down.
- **Minimal fix:**
  ```css
  @media (max-width:600px) and (pointer:coarse) {
    .keyboard-hint { display:none; }
  }
  ```
  Keep the actual shortcut available for hardware-keyboard users.

### 6. **Medium — Mobile composer actions leave Send stranded mid-row**
**Location:** `after/390x844-chat.png` — bottom of composer.

- **Failure scenario:** Preview context and Send cluster on the left, leaving a large unused area to the right. This breaks the desktop convention of locating the submit action at the composer’s trailing edge.
- **Minimal fix:**
  ```css
  .composer-actions {
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:12px;
    width:100%;
  }
  .composer-send { margin-left:auto; flex-shrink:0; }
  ```

### 7. **Medium — Provider control wastes a separate row on phones**
**Location:** `after/360x780-agent.png` — provider selector and Settings above task form.

- **Failure scenario:** Settings occupies a nearly empty full-width row immediately below the selector. Together, these controls consume roughly 90px before the task form.
- **Minimal fix:** At the phone breakpoint, use a flexible select and a 44px icon-only Settings button with an accessible name:
  ```css
  .provider-controls {
    display:grid;
    grid-template-columns:minmax(0,1fr) 44px;
    gap:8px;
  }
  .provider-controls select { min-width:0; width:100%; }
  ```
  Place the Provider label above the group.

### 8. **Medium — Long local path dominates the mobile task explanation**
**Location:** `after/360x780-agent.png` — text beneath “Run an agent task.”

- **Failure scenario:** A temporary Windows path wraps across multiple lines inside the explanation, delaying the important output and cancellation information.
- **Minimal fix:** Separate the path from the explanatory prose. Show the folder basename in a compact path chip with an explicit way to reveal or copy the full path:
  ```css
  .task-path {
    display:block;
    max-width:100%;
    overflow:hidden;
    white-space:nowrap;
    text-overflow:ellipsis;
  }
  ```
  Avoid hover-only disclosure on phones.

### 9. **Medium — Narrow inspector silently loses the Logs tab**
**Location:** `after/1920x1080-chat.png` versus `after/1440x900-chat.png` — inspector tab strip.

- **Failure scenario:** Logs is visible at 1920px but absent at 1440px, where Terminal is followed immediately by Close. No overflow affordance explains where Logs went.
- **Minimal fix:** Keep Close separate and make the tab group scrollable with a visible overflow affordance, or add a “More” menu:
  ```css
  .inspector-header { display:flex; }
  .inspector-tabs {
    display:flex;
    flex:1;
    min-width:0;
    overflow-x:auto;
    white-space:nowrap;
  }
  .inspector-close { flex:none; }
  ```
  The screenshot cannot establish whether Logs is currently clipped or conditionally omitted.

### 10. **Medium — Global Providers view gives substantial space to an unrelated saved note**
**Location:** `after/1440x900-providers.png` — right inspector.

- **Failure scenario:** While reviewing provider readiness, approximately 320px remains occupied by “Synthetic saved output.” Provider cards are compressed while the inspector offers no visible provider context.
- **Minimal fix:** Default the inspector to collapsed on this global view, or populate it with details of a selected provider:
  ```css
  .workspace[data-view="providers"][data-inspector="closed"] {
    grid-template-columns:var(--rail) var(--explorer) minmax(0,1fr);
  }
  ```
  Preserve an explicit control to reopen it.

### 11. **Medium — Provider pricing URL breaks in the middle of a word**
**Location:** `after/1440x900-providers.png` — OpenAI API card, “Incremental cost.”

- **Failure scenario:** The raw URL wraps as `.../pricin` followed by `g`, mixed into billing prose. Users must parse a dense block to find pricing information.
- **Minimal fix:** Replace the displayed URL with a concise “API pricing ↗” link; put verification information on a separate line:
  ```css
  .pricing-details { display:grid; gap:4px; min-width:0; }
  .pricing-link { white-space:nowrap; }
  ```
  Keep the full URL in the link destination.

### 12. **Medium — Budget comparison values do not share a baseline**
**Location:** `after/1024x768-evidence.png` — Mission budget and Runtime card rows.

- **Failure scenario:** “Outstanding reservations” wraps and pushes its amount below adjacent amounts. Runtime amounts likewise shift according to label length, weakening rapid side-by-side comparison.
- **Minimal fix:** Reserve the same two-line label space within each metric group:
  ```css
  .metric-label { line-height:18px; min-block-size:36px; }
  .metric-value { font-variant-numeric:tabular-nums; }
  .metric-card { display:flex; flex-direction:column; gap:6px; }
  ```

### 13. **Medium — Export including private material has the same visual treatment as public-only export**
**Location:** `after/768x1024-research.png` — export toolbar.

- **Failure scenario:** “Export (public sources only)” and “Export incl. private” use the same download icon and muted text-button styling. When scanning quickly, the materially different privacy scopes are easy to overlook.
- **Minimal fix:** Separate private export from the default action, use an explicit “Export including private sources…” label, and give it an outlined treatment:
  ```css
  .export-private {
    border:1px solid var(--border);
    border-radius:8px;
    padding:8px 12px;
  }
  .export-actions { display:flex; flex-wrap:wrap; gap:12px; }
  ```
  A scope-confirmation step would require interaction logic; its current presence is unknown.

### 14. **Medium — Tablet breadcrumbs truncate every useful level**
**Location:** `after/768x1024-research.png` — topbar.

- **Failure scenario:** The visible trail reads approximately “Ripple … / Resear… / Notebo…”. Neither project nor current destination remains fully legible, while the provider-status pill retains substantial width.
- **Minimal fix:** Collapse intermediate breadcrumb levels first and protect the current destination:
  ```css
  .breadcrumb-current { flex-shrink:0; white-space:nowrap; }
  .breadcrumb-project {
    min-width:0;
    overflow:hidden;
    text-overflow:ellipsis;
    white-space:nowrap;
  }
  @media (max-width:900px) {
    .breadcrumb-intermediate { display:none; }
    .topbar-provider-detail { display:none; }
  }
  ```

### 15. **Medium — File status takes space away from the file identity**
**Location:** `journey/4-api-answer-cost.png` — inspector, Project files card.

- **Failure scenario:** The filename is shortened to “journey-brief…” while the “extracted” badge occupies a wide pill with unused space. Users cannot read the extension or complete filename even for this short name.
- **Minimal fix:**
  ```css
  .file-header {
    display:grid;
    grid-template-columns:minmax(0,1fr) max-content;
    gap:8px;
  }
  .file-status { width:max-content; justify-self:end; }
  .file-name { overflow-wrap:anywhere; white-space:normal; }
  ```
  At narrow inspector widths, place status beneath the filename.

### 16. **Low — User messages have stronger surface emphasis than answers**
**Location:** `after/1920x1080-chat.png`, `after/1440x900-chat.png`, and `journey/4-api-answer-cost.png` — conversation cards.

- **Failure scenario:** The lighter raised user cards visually dominate the darker assistant cards. When scanning a completed conversation, the questions attract attention before the results.
- **Minimal fix:** Reduce the user-card surface emphasis and make answer content the stronger typographic anchor:
  ```css
  .message--user { background:var(--panel); }
  .message--assistant .message-body {
    font-size:14px;
    line-height:1.6;
  }
  ```
  Retain role labels; don’t rely on surface color alone.

### 17. **Low — Repeated simulation labels obscure the useful provider identity**
**Location:** `after/1440x900-chat.png` — topbar, project metadata, provider selector, response header, composer footer.

- **Failure scenario:** The route is repeatedly described as “simulated,” “simulated test route,” and “simulated (simulated) · simulated test.” The selector truncates redundant wording rather than presenting a concise choice.
- **Minimal fix:** Normalize the display name to “Simulated” with one secondary “Test route” badge. Keep one persistent next-send route indicator; remove duplicate project-header route text. Use:
  ```css
  .route-summary { display:flex; align-items:center; gap:8px; min-width:0; }
  ```
  This needs a small display-copy change as well as styling.

### 18. **Low — Project paths spend their available width on identical prefixes**
**Location:** `after/1440x900-chat.png` and `after/1024x768-evidence.png` — project-explorer subtitles.

- **Failure scenario:** Both paths truncate after `C:\Users\edwar\App...`, hiding the folder portion that would help distinguish projects. The subtitle adds visual density without useful differentiation.
- **Minimal fix:** Render a relative path or folder suffix in the explorer; expose the full path on demand. Keep truncation as a fallback:
  ```css
  .project-path {
    min-width:0;
    overflow:hidden;
    white-space:nowrap;
    text-overflow:ellipsis;
  }
  ```
  CSS ellipsis alone cannot choose the informative portion of the path.

---

### Not asserted from these captures

- **Mobile header clipping:** The phone captures begin partway through project controls. This could be a scrolled state rather than a fixed-header offset defect.
- **Missing scroll access:** Evidence and Providers extend below their panels, but screenshots cannot establish whether scrolling works.
- **Incorrect cost:** `$0.0000` appears for the API answer; pricing data is needed to distinguish a real zero from rounding or missing cost information.
- **Contrast compliance:** No numerical contrast failure is claimed without measuring the rendered text and background pairs.
