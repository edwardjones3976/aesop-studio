# Perplexity integrations

The `perplexity-orchestrator` route sends text chat to Perplexity's Orchestrator
API using Python's standard library. It is distinct from Studio's existing
Perplexity Sonar research-chat route. No SDK or database migration is required.

## Orchestrator

Configure `PERPLEXITY_API_KEY` through the existing process or Windows user
environment mechanism. Never paste the value into Studio chat or a report.
Readiness records presence, not successful endpoint access. The key is stripped
from CLI child-process environments. HTTP redirects are refused to keep bearer
credentials on the intended host; provider error bodies are not logged.

In Evidence -> Spend controls, set a monthly operating limit or enable the
mission permit. Both disabled means no Orchestrator chat request is sent. The
mission permit still resets on restart. The same atomic ledger and shared
envelopes used by the OpenAI API route apply.

Initial load, **Re-verify**, and individual route verification responses apply the same live spend-control overlay: with the mission permit on and monthly limit zero, Perplexity, Perplexity Orchestrator, and Codex API remain `READY_METERED`; turning the permit off with no monthly limit leaves them `READY_METERED_DISABLED`. Probing and metered send gates are unchanged.

Example: create a project with **Perplexity Orchestrator** as its provider, open
**Settings**, press **Refresh Perplexity models**, choose an entry from the Model
field's dropdown, save, and send `Reply with one sentence about rain.` Model IDs
come exclusively from authenticated `GET /orchestrator/v1/models`; there is no
invented default. A stale/unlisted selection blocks before chat dispatch. The
catalog is cached in memory for five minutes and isolated by key fingerprint;
refresh errors are shown without substituting a stale catalog. It is not written
to disk. Settings uses the existing project model override field.

Every chat request sends `stream: true`, `stream_options: {include_usage: true}`
and `max_completion_tokens: 2000` to
`https://api.perplexity.ai/orchestrator/v1/chat/completions`. The reservation
covers the UTF-8 input byte bound, message overhead, the highest catalog input
rate (including cache writes), the full output allowance and a 10% margin.
Reported cached prompt tokens use the discounted cache-read rate; completion
tokens include reasoning. The exact rates used for that reservation are also
used for settlement and recorded with its price source.

Cancelled, timed-out, output-capped, malformed, usage-free and interrupted
streams retain their reservations for owner reconciliation. Explicit HTTP
rejections settle at zero. No transport failure is replayed. An explicit 429
allows one recovery after Retry-After (seconds or HTTP date), within the original
deadline, and cancellation interrupts the backoff. If the interval exceeds the
deadline, the request fails without an early retry. HTTP 400 indicates an
invalid request/model; 402 indicates a tier restriction. Neither triggers a
fallback model. Cancellation stops local consumption promptly; a blocked socket
worker may remain until its bounded network timeout expires.

Pricing checked **2026-10-26** against
[Pricing](https://docs.perplexity.ai/docs/getting-started/pricing) and
[Orchestrator Models & Pricing](https://docs.perplexity.ai/docs/router/models).
Runtime prices are the authenticated catalog's `pricing.input`, `output`,
`cache_read`, and `cache_write`, in `usd_per_1m_tokens`; unknown units or invalid
rates are not dispatchable. Access depends on the key's current catalog and tier.
The current Orchestrator quickstart describes private-preview, open-weight
models. Access to any particular frontier model is unverified; the picker never
promises models absent from the key's catalog. Agent API has a separate catalog.

## Researcher Search

`researcher.research(store, query, **options)` accepts a string or one to five
queries. Each entry is independently normalized, bounded and redacted. Perplexity
receives the array in a single POST `/search`. Merged results are deduplicated by
URL, capped by `max_results` (1-20, default 5), and retain `date` and `last_updated`.

Example invocation, with a disposable Store or the caller's existing Store:

```python
from aesop_studio import researcher

result = researcher.research(
    store, ["solar panel recycling", "solar panel recycling research"],
    max_results=10, country="US", search_language_filter=["en"],
    search_domain_filter=["energy.gov"], search_after_date_filter="01/01/2026",
    last_updated_before_filter="10/27/2026", max_tokens=4000,
)
```

Supported filters follow the [Search API reference](https://docs.perplexity.ai/api-reference/search-post):
`country`, `search_domain_filter`, `search_language_filter`,
`search_after_date_filter`, `search_before_date_filter`,
`last_updated_after_filter`, `last_updated_before_filter`,
`search_recency_filter`, `max_tokens`, and `max_tokens_per_page`.
Dates use MM/DD/YYYY; domain inclusion and exclusion cannot be mixed.

**Brief/schema difference:** the published Search schema checked on 2026-10-26
does not contain `search_context_size`. Studio explicitly refuses that option
and directs callers to the documented content token budgets instead of sending
an undocumented field. The Search API supports raw results; the Agent API fits a
synthesized answer with citations. This change does not add Agent API or alter
the existing Sonar chat route.

Firecrawl remains first and Perplexity second. Firecrawl runs each query
separately and merges the URLs; Perplexity submits one multi-query request.
Explicit Perplexity-only filters skip Firecrawl without sending an unfiltered
request. Session cap 8 remains enforced by the roundtable broker; the daily cap
60 is now claimed atomically immediately before each HTTP attempt, including
429 recovery attempts and fallback calls. Invalid input consumes no quota.
The existing roundtable text command remains `RESEARCH: question`; batch and
filter options are available to Python callers rather than a new UI or grammar.

## Validation handoff

Repair order 1 (2026-10-26): lifecycle tests close each worker's thread-local
Store connection in `finally`, join workers before restoring request mocks and
before closing the main-thread Store, then remove the temporary directory.
Supervisor has no close/shutdown method; joining its test-owned workers is its
cleanup boundary here. A terminal task state alone does not prove its worker
has returned. No application shutdown API was added for test cleanup.

The limit regression covers both cold and cached catalogs. Runtime limits are
stored to two decimal places: `.0001` becomes zero, so the route blocks before
catalog lookup. A positive `.01` limit needs catalog prices to calculate the
reservation, then blocks at the atomic ledger ceiling check before any paid
POST. A warm catalog requires no HTTP request. These checks preserve the
reservation-before-send and unresolved-exposure behavior.

REA evidence: `capture_process_scenario` was requested for the focused test
command below with both offline environment flags. The client rejected it with
`MCP tool call requires approval, but approval policy is never`; no capture ran.
The advertised `trace_feature`/`trace_call_path` tools operate on procedures in
an opened binary, and `build_call_path` requires native function Evidence with
canonical addresses; they do not accept this Python source tree. Source reading
instead traced `Services.send -> Supervisor.create -> _start_api -> prices ->
catalog -> max_cost -> ledger.reserve -> _run_api -> stream -> _end -> settle`.
`Store.close()` closes only the calling thread's connection. This is source
evidence, not a REA runtime observation of the SQLite handle owner.

The repair run attempted the real interpreter directly; PowerShell reported
`CommandNotFoundException`, and a targeted `Get-Item` reported access denied
for that path. Python tests remain blocked in this sandbox. The Foreman must
run the following from this worktree; no repair test pass is claimed:

```powershell
$env:AESOP_PROBE_OFFLINE = '1'
$env:AESOP_SIMULATED_ROUTE = '1'
& 'C:\Users\edwar\AppData\Local\Python\pythoncore-3.14-64\python.exe' -W ignore -m unittest tests.test_perplexity
& 'C:\Users\edwar\AppData\Local\Python\pythoncore-3.14-64\python.exe' -W ignore -m unittest discover -s tests -p 'test_*.py'
```

Repair static checks: `node --check static/app.js` and `git diff --check`
exited 0. Because this test file and these notes are still untracked, each was
also checked with `git diff --no-index --check -- /dev/null <file>`: no whitespace
errors were reported (exit 1 indicates the new-file difference; Git also warned
about LF-to-CRLF conversion). No commit, push, PR mutation or live request ran.

The earlier author-run record follows for provenance:

All HTTP tests mock the network and use disposable stores. Run from this branch:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_tests.ps1
python -W ignore -m unittest tests.test_perplexity -v
node --check static/app.js
git diff --check
```

During this author run, `python --version` and the named full-suite command were
denied by the sandbox: the WindowsApps `python.exe` alias could not be accessed.
`uv python find --no-python-downloads` was also denied. The dispatcher must run
the full-suite command above with an accessible Python 3.11+ interpreter; no
Python test pass is claimed. Browser interaction QA also requires starting an
isolated server with a disposable data directory, never the owner's live data.

Smoke status: **smoke test pending key**. The process environment had no
`PERPLEXITY_API_KEY`; no credential lookup or paid endpoint smoke was attempted.
Once the owner supplies it separately, make one catalog GET, one minimal capped
Orchestrator chat through a temporary Studio Store with a deliberate spend
envelope, and one Search POST with `max_results: 1`. Report only HTTP status or
response shape. Do not replay an ambiguous result or print catalog contents or
credentials. None of this is deployment or independent exact-head acceptance.

Author/provenance: OpenAI Codex, GPT-6 (exact serving variant unavailable to this
session), branch `codex/perplexity-orchestrator`, base/unchanged HEAD
`1cf40405f921ea9460f370480c096b222a68eb73`. No submission headers or contribution
envelopes were added. The authorized explicit-file `git add` was denied because
the sandbox cannot create the primary repository's worktree `index.lock`.
Commit and push were not performed. After tests pass, the supervised dispatcher
must stage only the eight integration files, commit on this branch, push it and
obtain one non-author review at the resulting exact head. Runtime invocation
also generated an untracked `%SystemDrive%` Windows cache directory; automatic
approval review rejected its cleanup as blocked by policy. Exclude that directory
from the commit.
