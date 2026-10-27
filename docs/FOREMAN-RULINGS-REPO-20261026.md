# Foreman rulings for the end-to-end repo order (2026-10-26)

Owner, 2026-10-26: "Use your best judgment." These two items were left open in the work order; they are now decided. Cursor: write these into `docs/LICENSE-DECISION.md` and `docs/REPO-SETTINGS.md` as settled, not as questions.

## License: none, all rights reserved (for now)

The repository is private and Aesop Studio is the owner's personal tool. No open-source license is granted. Add a short `LICENSE` file stating: "Copyright (c) 2026 Edward Jones. All rights reserved. No license is granted to use, copy, modify or distribute this software." Record in `docs/LICENSE-DECISION.md` that MIT or Apache-2.0 can replace it in one commit if the owner later shares the project.

## Branch protection on `main`: apply

- Require the CI status check(s) from `.github/workflows/ci.yml` to pass before merging.
- Require 1 approving review; dismiss stale approvals on new commits.
- No force-pushes; no deletions of `main`.
- Delete head branches automatically after merge.
- Admins included (the owner can still override with an explicit bypass when needed).

If `gh api` can set these without an admin confirmation prompt, apply them and paste the receipt in your hand-in; otherwise leave the exact `gh api` commands in `docs/REPO-SETTINGS.md` and the Foreman applies them after your PR's CI run exists (the check name is needed).
