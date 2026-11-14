# Go public — 2026-10-27

Cursor, under the Foreman work order of 2026-10-26 (late evening PT). Visibility changes use the logged-in `gh` account `edwardjones3976`. No history was rewritten. No excluded repository was cloned or changed.

Scan tool: `gitleaks` is not on PATH. Every candidate below was mirror-cloned to `C:\Users\edwar\.cursor-scratch\gopublic\<repo>.git` and scanned with `git log -p --all` (every commit, branch, and tag) through a regex set for `sk-`, `sk-ant-`, `pplx-`, `fc-`, `fc-live-`, `gh[pousr]_`, `xox[abprs]-`, `AKIA`, `AIza`, private-key blocks, password/passwd/secret/token assignments, `.env` / `*.pem` / `*.p12` / `*.pfx` / `id_rsa` paths, `@gmail.com` / `@yahoo.com` addresses other than the owner, absolute paths whose username is not the owner's, and DPAPI or credential-store blobs.

Owner addresses treated as the owner's, not as hits: `edward.jones3976@yahoo.com`, `edward.jones3976@gmail.com`, `edj096587@gmail.com`.

## Excluded — not touched

| Repo | Verdict |
|---|---|
| job-search | Excluded by the work order. Not cloned, not scanned, still private. |
| edge_engine | Excluded by the work order. Not cloned, not scanned, still private. |
| rootwitness | Excluded after the README and PRD. It is a genealogy engine whose PRD states that development starts from the owner's own tree, that living-person data is sensitive, and that family-lineage research docs live in the tree. Not scanned further, not flipped. Still private. |

Already public, no action: DOGma, LeagueManager, vending-machine-system.

## aesop-studio

- Scan: regex over `git log -p --all`. Commits scanned: 74. Paths seen: 214.
- Hits: test fixtures only. Examples: `tok_test_rate_1234567890`, `tok_valid_123456`, `sk-proj-abcdefghijklmnopqrstu`, `sk-real-looking-key-0000000000`, alphabet-run `ghp_` / `pplx-` / `fc-` strings in tests, and a PEM header whose body is the short fixture `MIIBOgIBAAJB`. `.env.example` uses the placeholder path `C:/Users/you/`. DPAPI mentions are source paths, not credential blobs. No `.env`, `.pem`, `.p12`, `.pfx`, or `id_rsa` in history. No non-owner gmail or yahoo address.
- Verdict: clean. LICENSE already on `main` (all rights reserved). No license pull request.
- Flipped: yes. Confirmation: `visibility=public`, `private=false` (`gh api repos/edwardjones3976/aesop-studio`).
- CI: the two latest failed runs are startup failures and GitHub will not retry them. Exact messages: `run 40452784603 cannot be rerun; This workflow run cannot be retried` and the same for `40452779326`. Both have workflow path `BuildFailed`. The newest real CI run GitHub would retry is `40437469144` (rerun attempt 2). Its jobs started at `2026-10-27T05:51:02Z` and finished with conclusion `failure`, not `startup_failure`. Log download returned `log not found: 122034611286`, so the failing step text was not retrieved. Actions did start after the flip.

## director-orchestrator

- Scan: same regex. Commits scanned: 2624. Paths seen: 873.
- Hits reviewed, none are a real secret:
  - `sk-evi…` (len 36 and 25) in `tests/test_secret_hygiene_pattern.py` and `projects/homemade-llm/project-state-report.md` is the letter sequence inside a work-order id that contains `task-evidence`, not an API key.
  - Slack `xoxb-` values in tests are synthetic words (`xoxb-sy…`, len 24, all letters) next to `xapp-synthetic-committee`.
  - `.env*.example` secret fields are `REPLACE_WITH_RANDOM_SECRET` or `REPLACE_WITH_DISTINCT_RANDOM_SECRET`. Provider API key fields are empty. Slack channel and user ids are filled; those are identifiers, not tokens.
  - Paths: `/home/node` in Docker files, `C:\Users\owner` and `C:\Users\coordinator` in tests, and `/home/u/.ssh/key` inside a synthetic error string in `projects/homemade-llm/train/test_smoke_train.py`. No credential value is stored on those paths.
  - Private-key hit is the header line only (len 31) in a test.
  - No non-owner personal gmail or yahoo address. Other addresses are example, invalid, bot, or `codex@openai.com`.
- Verdict: clean under the extra rule (no real secret, no private host path carrying a credential, no other person's personal email).
- LICENSE was absent on `main`. Added on branch `cursor/license-all-rights-reserved-20261027`. Pull request (not merged): https://github.com/edwardjones3976/director-orchestrator/pull/522
- Flipped: yes. Confirmation: `visibility=public`, `private=false`.

## aesop-learning-lab

- Scan: same regex. Commits scanned: 262. Paths seen: 265.
- Hits: none (no key shape, no secret assignment, no non-owner email, no foreign user path, no private-key body, no sensitive filename).
- Note, not a secret: README links a ChatGPT share URL.
- Verdict: clean.
- LICENSE was absent on `master`. Pull request (not merged): https://github.com/edwardjones3976/aesop-learning-lab/pull/78
- Flipped: yes. Confirmation: `visibility=public`, `private=false`.

## Project-Uppercut

- Scan: same regex. Commits scanned: 365. Paths seen: 835.
- Hits: one key-shaped fixture (counted in the fixture class) and `/home/node` in `director-orchestrator/docker-compose.yml`. Nested `.env.example` files use `REPLACE_WITH_RANDOM_SECRET`. `.mcp.json` points at `http://127.0.0.1:8000/mcp` only.
- Verdict: clean.
- LICENSE was absent on `main`. Pull request (not merged): https://github.com/edwardjones3976/Project-Uppercut/pull/60
- Flipped: yes. Confirmation: `visibility=public`, `private=false`.

## long-table-bid-whist

- Scan: same regex. Commits scanned: 149. Paths seen: 451.
- Hits: `services/table-authority/tests/credentials.test.ts` holds the literals `tok-dealer-as-south` and `tok-dealer-as-host`. Two secret-assignment hits were the same class of test literal. No key shape, no foreign email, no private-key body.
- Verdict: clean.
- LICENSE was absent on `main`. Pull request (not merged): https://github.com/edwardjones3976/long-table-bid-whist/pull/4
- Flipped: yes. Confirmation: `visibility=public`, `private=false`.

## HelloWorld

- Scan: same regex. Commits scanned: 1. Paths seen: 52.
- Hits: none.
- Verdict: clean.
- LICENSE was absent on `master`. Pull request (not merged): https://github.com/edwardjones3976/HelloWorld/pull/1
- Flipped: yes. Confirmation: `visibility=public`, `private=false`.

## desktop-tutorial

- Scan: same regex. Commits scanned: 2. Paths seen: 1 (`README.md`).
- Hits: none.
- Verdict: clean.
- LICENSE was absent on `main`. Pull request (not merged): https://github.com/edwardjones3976/desktop-tutorial/pull/1
- Flipped: yes. Confirmation: `visibility=public`, `private=false`.

## Still private

job-search, edge_engine, rootwitness.
