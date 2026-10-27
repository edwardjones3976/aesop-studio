# GitHub repository settings (Foreman ruling 2026-10-26)

Apply on **https://github.com/edwardjones3976/aesop-studio** for branch `main`. CI workflow: `.github/workflows/ci.yml`.

## Branch protection for `main` (required)

- **Require status checks to pass** — all required `test (...)` matrix jobs you care about, plus `secret scan (diff)`, from `.github/workflows/ci.yml`.
- **Require pull request reviews** — **1** approving review; dismiss stale approvals when new commits are pushed.
- **No force-pushes** to `main`; do not allow branch deletion for `main`.
- **Include administrators** in the rules (owner may bypass explicitly when needed).
- **Automatically delete head branches** after merge (*Settings → General → Pull Requests*).

### Owner / Foreman checklist

- [ ] Protection rule applied on `main` (UI or `gh api` receipt below).
- [ ] Required status check contexts match the names GitHub shows after the first CI run on this PR.

## Repository hygiene

- Default branch: `main`.
- License: all rights reserved (`LICENSE`, `docs/LICENSE-DECISION.md`). Repository stays **private** unless the owner decides otherwise.

## Branches to delete (manual, when ready)

- `codex/perplexity-orchestrator` — already fast-forwarded into `main`; safe to delete on GitHub when you no longer need the name.

Do **not** delete `codex/browser-v2-antigravity` until browser v2 repair lands.

## Automation note

If `gh api` can set branch protection without elevated admin confirmation, a maintainer may apply rules and paste the API response here as a receipt. Otherwise complete the checklist in the GitHub UI.

### Suggested `gh` commands (owner runs if permitted)

```powershell
gh api repos/edwardjones3976/aesop-studio/branches/main/protection -X PUT -f required_status_checks[strict]=true `
  -f enforce_admins=true -f required_pull_request_reviews[required_approving_review_count]=1 `
  -f restrictions=null
```

Adjust `required_status_checks` contexts to match the exact check names GitHub shows after the first CI run on `main`.
