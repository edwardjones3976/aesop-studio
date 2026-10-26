"""Roundtable Researcher: a callable public-web research lane for roundtables and the War Room.

Speakers (or the owner) ask with a `RESEARCH: <question>` line; the broker runs one bounded web search and posts
the sources back into the timeline as a Researcher event that everyone can cite. The researcher never speaks for
itself, never counts as a speaker, and never sees the transcript: only the query text leaves this machine.

Backends, first available wins: Firecrawl search (FIRECRAWL_API_KEY), then Perplexity search
(PERPLEXITY_API_KEY). Keys are read from the process or the Windows user environment and are never logged.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import time
import urllib.error
import urllib.request

from .security import redact

MAX_QUERY = 300
MAX_RESULTS = 5
TIMEOUT_S = 45
SESSION_CAP = 8          # research calls per roundtable session (default; the draft can lower it)
DAILY_CAP = 60           # research calls per day across Studio
REQUEST_RE = re.compile(r"^\s*(?:[-*>]\s*)?(?:\**RESEARCH\s*[:\-]\s*\**|@Researcher\b[,:]?)\s*(.+?)\s*$", re.I | re.M)
BACKENDS = ("firecrawl", "perplexity")
# `RESEARCH: study <reference> <topic>` asks for a reference study (R.E.A., local static inspection) instead of a web search
STUDY_RE = re.compile(r"^\s*study\s+(?:of\s+)?(?:\"([^\"]+)\"|'([^']+)'|([^\s:]+))\s*:?\s+(.+)$", re.I)
_ENDPOINT = {"firecrawl": "https://api.firecrawl.dev/v2/search", "perplexity": "https://api.perplexity.ai/search"}
_KEY = {"firecrawl": "FIRECRAWL_API_KEY", "perplexity": "PERPLEXITY_API_KEY"}
DISPLAY = {"firecrawl": "Firecrawl", "perplexity": "Perplexity"}


def _key(name: str) -> str:
    v = os.environ.get(name, "")
    if not v and os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                v = str(winreg.QueryValueEx(k, name)[0] or "")
        except OSError:
            v = ""
    return v.strip()


def backends() -> list[str]:
    if os.environ.get("AESOP_SIM_RESEARCH") == "1":
        return ["simulated"]
    if os.environ.get("AESOP_PROBE_OFFLINE") == "1":  # tests and QA never reach a real search API
        return []
    return [b for b in BACKENDS if _key(_KEY[b])]


def status() -> dict:
    b = backends()
    return {"available": bool(b), "backends": b, "names": [DISPLAY.get(x, x) for x in b],
            "session_cap": SESSION_CAP, "daily_cap": DAILY_CAP,
            "note": ("Public web search only: just the query text is sent." if b else
                     "No research key found. Set FIRECRAWL_API_KEY or PERPLEXITY_API_KEY to enable the Researcher.")}


def requests_in(text: str) -> list[str]:
    """`RESEARCH: question` lines in a speaker message (cleaned, deduplicated)."""
    out = []
    for m in REQUEST_RE.finditer(text or ""):
        q = re.sub(r"\s+", " ", m.group(1)).strip().strip('"').strip()
        if len(q) >= 4 and q.lower() not in (x.lower() for x in out):
            out.append(q[:MAX_QUERY])
    return out


def study_request(query: str) -> tuple[str, str] | None:
    """(reference name, topic) when a research line asks for a reference study, else None."""
    m = STUDY_RE.match(query or "")
    if not m:
        return None
    name = (m.group(1) or m.group(2) or m.group(3) or "").strip()
    topic = " ".join(m.group(4).split()).strip()
    return (name, topic) if name and len(topic) >= 3 else None


def _post(url: str, body: dict, key: str, before_send=None) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                          "User-Agent": "AesopStudio-Researcher/1"})
    try:
        if url.startswith("https://api.perplexity.ai/"):
            from .perplexity_api import response
            opened = response(req, TIMEOUT_S, on_attempt=before_send)
        else:
            if before_send:
                before_send()
            opened = urllib.request.urlopen(req, timeout=TIMEOUT_S)
        with opened as r:
            return json.loads(r.read(2_000_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = e.read(400).decode("utf-8", "replace") if e.fp else ""
        raise RuntimeError(f"HTTP {e.code}: {redact(detail)[:200]}") from None


def search_body(query, max_results=MAX_RESULTS, **options) -> dict:
    """Validate documented Search API inputs before taking quota or sending anything."""
    queries = query if isinstance(query, list) else [query]
    if not 1 <= len(queries) <= 5 or any(not isinstance(q, str) or not q.strip() for q in queries):
        raise ValueError("search requires one to five nonempty queries")
    queries = [redact(re.sub(r"\s+", " ", q).strip())[:MAX_QUERY] for q in queries]
    if type(max_results) is not int or not 1 <= max_results <= 20:
        raise ValueError("max_results must be an integer from 1 to 20")
    body = {"query": queries if isinstance(query, list) else queries[0], "max_results": max_results}
    dates = {"search_after_date_filter", "search_before_date_filter", "last_updated_after_filter",
             "last_updated_before_filter"}
    allowed = dates | {"country", "search_domain_filter", "search_language_filter", "search_recency_filter",
                       "max_tokens", "max_tokens_per_page"}
    if "search_context_size" in options:
        raise ValueError("search_context_size is not in the current Search API schema; use max_tokens or max_tokens_per_page")
    if options.keys() - allowed:
        raise ValueError("unsupported Search API filter")
    for name, value in options.items():
        if name in dates:
            if not isinstance(value, str) or not re.fullmatch(r"\d{2}/\d{2}/\d{4}", value):
                raise ValueError("date filters require MM/DD/YYYY")
            datetime.datetime.strptime(value, "%m/%d/%Y")
        elif name == "country":
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]{2}", value):
                raise ValueError("country requires an ISO 3166-1 alpha-2 code")
            value = value.upper()
        elif name in ("max_tokens", "max_tokens_per_page"):
            if type(value) is not int or not 1 <= value <= 1_000_000:
                raise ValueError("content token budgets must be integers from 1 to 1000000")
        elif name == "search_recency_filter":
            if value not in ("hour", "day", "week", "month", "year"):
                raise ValueError("unsupported recency filter")
        else:
            if not isinstance(value, list) or not 1 <= len(value) <= 20 or any(not isinstance(v, str) for v in value):
                raise ValueError("domain/language filters require one to twenty strings")
            if name == "search_language_filter" and any(not re.fullmatch(r"[a-z]{2}", v) for v in value):
                raise ValueError("language filters require ISO 639-1 codes")
            if name == "search_domain_filter":
                if any(not v or v in ("-", ".") or len(v) > 253 or "://" in v or any(c.isspace() for c in v) for v in value):
                    raise ValueError("invalid search domain")
                if len({v.startswith("-") for v in value}) > 1:
                    raise ValueError("use included or excluded domains, not both")
        body[name] = value
    return body


def _merge(results, limit):
    unique = {}
    for row in results:
        if row.get("url") and row["url"] not in unique:
            unique[row["url"]] = row
    return list(unique.values())[:limit]


def _search(backend: str, query, *, before_send=None, **options) -> list[dict]:
    body = search_body(query, **options)
    query = body["query"]
    if backend == "simulated":
        if before_send:
            before_send()
        return [{"title": f"Simulated source {i} for {query[:40]}", "url": f"https://example.org/{i}",
                 "snippet": f"Synthetic finding {i} about {query[:60]}."} for i in (1, 2, 3)]
    key = _key(_KEY[backend])
    if backend == "firecrawl":
        if set(body) - {"query", "max_results"}:
            raise ValueError("advanced search filters require the Perplexity backend")
        if isinstance(query, list):
            return _merge([r for q in query for r in _search(backend, q, before_send=before_send, **options)], body["max_results"])
        payload = {"query": query, "limit": body["max_results"], "sources": ["web"]}
        d = _post(_ENDPOINT[backend], payload, key, before_send=before_send) if before_send else _post(_ENDPOINT[backend], payload, key)
        if d.get("success") is False:
            raise RuntimeError(str(d.get("error") or "unsuccessful search")[:200])
        data = d.get("data")
        web = data.get("web") if isinstance(data, dict) else data if isinstance(data, list) else []
        return [{"title": w.get("title") or w.get("url"), "url": w.get("url"),
                 "snippet": w.get("description") or w.get("snippet") or (w.get("markdown") or "")[:300]}
                for w in (web or []) if isinstance(w, dict) and w.get("url")]
    d = _post(_ENDPOINT[backend], body, key, before_send=before_send) if before_send else _post(_ENDPOINT[backend], body, key)
    return _merge([{"title": w.get("title") or w.get("url"), "url": w.get("url"), "snippet": w.get("snippet") or "",
                    "date": w.get("date"), "last_updated": w.get("last_updated")}
                   for w in d.get("results", []) if isinstance(w, dict) and w.get("url")], body["max_results"])


def daily_used(store) -> int:
    row = store.one("SELECT v FROM kv WHERE k=?", (f"research_calls:{time.strftime('%Y-%m-%d')}",))
    return int(row["v"]) if row else 0


def _bump(store) -> None:
    k = f"research_calls:{time.strftime('%Y-%m-%d')}"
    with store.tx() as c:
        row = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        if row and int(row[0]) >= DAILY_CAP:
            raise RuntimeError(f"daily research cap ({DAILY_CAP}) reached")
        c.execute("INSERT INTO kv(k,v) VALUES(?, '1') ON CONFLICT(k) DO UPDATE SET v=CAST(v AS INTEGER)+1", (k,))


def research(store, query, **options) -> dict:
    """One bounded public search. Returns {ok, backend, query, results, latency_s, error}."""
    t0 = time.time()
    try:
        body = search_body(query, **options)
    except ValueError as e:
        return {"ok": False, "query": "", "results": [], "error": str(e), "latency_s": 0}
    query = body["query"]
    label = "; ".join(query) if isinstance(query, list) else query
    if daily_used(store) >= DAILY_CAP:
        return {"ok": False, "query": label, "results": [], "error": f"daily research cap ({DAILY_CAP}) reached",
                "latency_s": 0}
    errors = []
    for b in backends():
        try:
            res = _search(b, query, before_send=lambda: _bump(store), **options)[:body["max_results"]]
            out = {"ok": True, "backend": b, "query": label, "results": res, "latency_s": round(time.time() - t0, 2)}
            store.event("research_call", None, backend=b, results=len(res), latency_s=out["latency_s"])
            return out
        except (OSError, RuntimeError, ValueError) as e:
            errors.append(f"{DISPLAY.get(b, b)}: {type(e).__name__}: {redact(str(e))[:160]}")
    err = "; ".join(errors) or status()["note"]
    store.event("research_call", None, backend=None, ok=False)
    return {"ok": False, "query": label, "results": [], "error": err, "latency_s": round(time.time() - t0, 2)}


def _clean(t: str) -> str:
    """Page snippets arrive as Markdown fragments: keep the words, drop links, images, headings and emphasis."""
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"(^|\s)#{1,6}\s+", r"\1", t)
    t = re.sub(r"[*_`]{1,3}", "", t)
    return re.sub(r"\s+", " ", t).strip()


def render(res: dict, asked_by: str) -> str:
    """Timeline text for a research result (Markdown the room renders; plain enough for CLI speakers)."""
    head = f"**Research for {asked_by}:** {res['query']}"
    if not res["ok"]:
        return f"{head}\n\nNo results: {res['error']}"
    if not res["results"]:
        return f"{head}\n\nThe search returned no sources."
    lines = [head, f"_Source: {DISPLAY.get(res['backend'], res['backend'])} web search, {len(res['results'])} result(s). "
                   "Snippets are quoted from the pages; verify before relying on them._", ""]
    for i, r in enumerate(res["results"], 1):
        snip = _clean(redact(str(r.get("snippet") or "")))
        lines.append(f"{i}. **{_clean(redact(str(r.get('title') or 'Untitled')))[:140]}** — {redact(str(r['url']))[:300]}"
                     + (f" ({r['date']})" if r.get("date") else ""))
        if snip:
            lines.append(f"   {snip[:420]}")
    return "\n".join(lines)
