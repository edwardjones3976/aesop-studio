# QA hygiene follow-up (Foreman, 2026-10-27) — for a provider, after the billing lock clears

First run of the new QA toolkit (`ruff`, `bandit`, `gitleaks`, `actionlint`) on `main` at `d847957`:

- **gitleaks, full history (all refs):** clean. 10 raw hits, all fixtures: Studio's test pairing tokens (`tok_test_…`, `tok_valid…`) and the PEM fixture in `tests/test_hardening.py`. The scan allowlist now recognises them. Nothing real; the public flip was safe.
- **actionlint:** `.github/workflows/ci.yml` clean.
- **bandit (medium+):** 8 findings, all false positives, worth annotating so the next run is quiet:
  - `B608` ×7 (`backup.py:94,158`, `roundtable_live.py:110`, `services.py:169`, `tasks.py:255,302,743`): dynamic *column names* from fixed allowlists joined into `k=?`; values are bound with `?`. Add `# nosec B608 - column names from a fixed allowlist, values bound` on each.
  - `B310` (`researcher.py:95`): `urlopen` on a validated `https://` URL. Add `# nosec B310 - scheme validated above`.
- **ruff:** 117 auto-fixable findings (`ruff check --fix`), dominated by `RUF100` (unused `noqa`) ×76, `I001` (import order) ×19, `FURB167`, `PLW1510` (`subprocess.run` without `check=`) ×12, `BLE001` (blind `except`) ×10, `F401` (unused imports) ×5. The `PLW1510` and `BLE001` ones deserve a human look (some blind excepts are deliberate "never let a watcher die" guards and should get `# noqa: BLE001` with the reason, not a behaviour change).

Order shape: one provider, one PR, `ruff check --fix` + `ruff format`, the `nosec`/`noqa` annotations with reasons, **no behaviour change**, full suite green. Writer: Codex (maintenance routing). Reviewer: Cursor (Warden). Blocked until GitHub Actions is unlocked (WO-20261027-004), since the PR cannot pass protection before then.
