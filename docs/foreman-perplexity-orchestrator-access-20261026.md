# Work order — request Perplexity Orchestrator access (Codex)

**Issued by:** Claude, Foreman (BlackBox), 2026-10-26
**Assigned to:** Codex, in an interactive Codex CLI session on BlackBox, supervised by the owner
**Owner's instruction, verbatim:** "Have Codex request Orchestrator access for my key"

## Why

The owner's Perplexity API key works for the Search API: the Foreman's smoke test returned 3 results. `GET https://api.perplexity.ai/orchestrator/v1/models` returns **HTTP 403** for the same key. Perplexity's docs state "Orchestrator API is in private preview" (https://docs.perplexity.ai/docs/router/quickstart). The API platform page states "Some APIs, including Orchestrator, require separate access approval" (https://www.perplexity.ai/api-platform). Aesop Studio already has the Orchestrator route on `main` (`6c99527`), off until access is granted and a monthly limit is set.

## Task

1. In the owner's signed-in Perplexity API console (console.perplexity.ai, or the API settings in their open Edge tab), find how to request Orchestrator (private preview) access: a request or waitlist button, form or contact path. Start from https://www.perplexity.ai/api-platform and the Orchestrator docs above.
2. Request access for the owner's account or organization and API key.
   - Use plainly true answers.
   - Use case: "Aesop Studio, a personal local-first AI workspace that routes chat to frontier models through one key, with per-request spend reservation and a monthly limit."
   - Expected volume: low, single owner.
3. **Before submitting,** show the owner the exact form contents in this window and get their OK. If the form asks to accept new terms, or to buy, upgrade or add a payment method, stop and get the owner's approval of exactly that first.
4. Never print, paste or log the API key.

## Report

Fill in "Codex result" below:
- where access was requested;
- what was submitted (no key material);
- the confirmation or reference shown;
- the expected wait, if stated.

When access is granted, rerun the Foreman's smoke test. The models call should return 200, and one tiny chat should complete.

## Codex result

**Status: SUPPORT REPLIED — NO PREVIEW ACCESS; REQUEST-PATH DOCUMENTATION CONFLICT.**

- Acting session: interactive OpenAI Codex session, 2026-10-26. Receipt recorded
  at 2026-10-26 21:25:38 UTC.
- Official request path: the API platform's Orchestrator **Request access** link
  leads to the [Orchestrator quickstart](https://docs.perplexity.ai/docs/router/quickstart),
  which directs private-preview access requests to **api@perplexity.ai** by email.
- Verified the console and Gmail are signed in as **edward.jones3976@gmail.com**.
  The existing console project was **Ollama-Home-Rig**, project **67795716**.
- Showed the owner the complete project form and exact email contents in this
  session. The owner approved both with **"ok"** before submission.
- Created the dedicated [Aesop Studio project](https://console.perplexity.ai/project/8d7f9d1c-52ea-477f-9231-b23ef68d5031),
  ID **8d7f9d1c-52ea-477f-9231-b23ef68d5031**, with the reviewed name, country
  and owner-entered ZIP. Invoice address and tax details were not entered.
- After project creation, the console opened an **Add credits** form offering
  **$10** with auto-refill selected. Closed it without accepting auto-refill,
  adding a payment method or purchasing credits. The new project's home page
  showed **$0.00** and **Turn on auto-refill** afterward.
- Sent the exact approved email from **edward.jones3976@gmail.com** to
  **api@perplexity.ai**, subject
  **Request for Orchestrator API private-preview access - Aesop Studio**.
  It requests access for the account and existing key, names Aesop Studio as the
  requested dedicated project and the previous console project as context,
  includes the work order's exact use case and low single-owner volume,
  describes the prior Search success / Orchestrator 403, and asks whether access
  is account-wide or project-specific and what wait to expect. No CC, BCC or
  attachments were added. No unapproved project ID was added to the email.
- Confirmation: Gmail displayed **Message sent**. Opened and verified the
  [sent message](https://mail.google.com/mail/u/0/#sent/QgrcJHsbflhZZlgcdBHFBbBSsgfSgXPjqGq),
  dated **October 26, 2026, 2:24 PM America/Los_Angeles (21:24 UTC)**.
  This confirmed Gmail sent it. The support reply recorded below supersedes the
  initial acknowledgment-unknown state. Expected wait: **not stated**.
- No API key was read, printed, pasted or logged. No new key, payment, upgrade,
  terms acceptance or live API request was performed.
- Local evidence directory:
  `C:\Users\edwar\.codex\artifacts\perplexity-orchestrator-access-20261026`.
  `request-preview.txt` preserves the exact approved contents;
  `new-project-preview.jpg` and `email-preview.jpg` preserve the approval views;
  `project-created.jpg` and `email-sent.jpg` preserve the completed UI states.
- The catalog GET and tiny chat remain pending an access grant and the required
  spend controls. Creating a project and sending this request do not establish
  that the existing key can use the new project or Orchestrator.

### Claude / Foreman notification

The owner subsequently instructed: **"Please inform Claude/Foreman as well"**.
Sent the completion handoff through `mcp__director_claude__claude_ask` after
the native Claude contact reported enabled. Claude received the supplied
submission facts, project ID, receipt links, purchase dismissal, credential
boundary and pending-access status. It returned **REQUEST SENT, ACCESS GRANT
PENDING** and confirmed the later smoke checks stay under this existing work
order and its spend controls, with no new blanket approval requirement.

Claude raised an account-email concern, then withdrew it after receiving the
executing session's evidence that the Perplexity account and Gmail sender both
matched. No corrective email was sent. One detailed clarification was refused
by the contact's credential-binding filter; a shorter notice containing no
credential material was accepted and returned the corrected disposition.

**Delivery limit:** the native contact explicitly identified itself as separate
from the original BlackBox Foreman session and stated it had not delivered to
that session. This is a Claude-contact acknowledgment, not original-session
receipt or independent verification. This work-order update is the durable
async handoff for the original Foreman; its read/acknowledgment is unconfirmed.

Full notification and corrected response:
`C:\Users\edwar\.codex\artifacts\perplexity-orchestrator-access-20261026\claude-notification-receipt.json`.

### Perplexity support reply found in the exact thread

The owner reported that the email was returned. Opened the original subject
thread in Gmail and found an actual reply, not a delivery-failure notice:
**Sage from API Platform**, `david@api-platform.intercom-mail.com`, signed
**Sage, AI Support Agent**, dated **2026-10-26 14:25 America/Los_Angeles
(21:25 UTC)**. The reply refers specifically to Aesop Studio and the models
endpoint's 403. It establishes that the request reached Perplexity support;
it is not an access grant or independent technical verification.

Support says there is currently no Orchestrator sign-up form, waitlist or
separate email application path, and that broader availability will appear in
the docs changelog. It attributes the 403 to missing private-preview access,
not billing or credits, and cannot confirm account-wide versus project-specific
approval. It suggests Agent API as an alternative. That suggestion is recorded
only; no migration, provider call, credit purchase or follow-up email ran.

Reopened the official Orchestrator quickstart during this readback. It still
instructs users to email `api@perplexity.ai` to request preview access. This
conflicts with the AI support reply. Preserve that discrepancy; do not treat
the request as queued, assume a wait estimate, or imply payment would grant
preview access. No approval or queue/reference number was provided.

The reply is in the same Gmail conversation linked above. Local evidence:
`C:\Users\edwar\.codex\artifacts\perplexity-orchestrator-access-20261026\perplexity-support-reply.txt`
and `perplexity-support-reply.jpg` in the same directory. The catalog GET and
tiny chat remain gated on an actual access grant and the existing spend rules.

Sent a material status-correction notice through the same native Claude contact
under the owner's existing notification instruction. The connector timed out
after 300 seconds. Delivery/acknowledgment for this correction is **unconfirmed**;
it was not replayed. This updated work order remains the durable async handoff.
Contact evidence: `claude-support-update-receipt.json` in the local evidence
directory above.
