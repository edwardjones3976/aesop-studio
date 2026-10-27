## Summary

What changed and why (link `docs/` rulings or Foreman notes if applicable).

## Rulings / scope

- [ ] No change to metered-route billing behavior unless explicitly ruled
- [ ] Loopback-only and credential rules preserved

## Tests run

- [ ] `.\scripts\run_tests.ps1` (or equivalent `unittest discover` with `AESOP_PROBE_OFFLINE=1` and `AESOP_SIMULATED_ROUTE=1`)
- [ ] `node --check static/app.js`
- [ ] Extension / JS tests (if this branch includes `extension/` or `tests/js/`)

## Live checks (if any)

Describe Foreman or owner live verification (providers, browser, etc.), or write **N/A** for docs-only changes.

## Credentials

- [ ] **No credential material** in commits, PR text, or attached files (no keys, tokens, or `.env` contents)
