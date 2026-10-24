"""Roundtable Researcher: a callable public-web research lane for roundtables and the War Room.

Speakers (or the owner) ask with a `RESEARCH: <question>` line; the broker runs one bounded web search and posts
the sources back into the timeline as a Researcher event that everyone can cite. The researcher never speaks for
itself, never counts as a speaker, and never sees the transcript: only the query text leaves this machine.

Backends, first available wins: Firecrawl search (FIRECRAWL_API_KEY), then Perplexity search
(PERPLEXITY_API_KEY). Keys are read from the process or the Windows user environment and are never logged.
"""
from __future__ import annotations

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


def _post(url: str, body: dict, key: str) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                          "User-Agent": "AesopStudio-Researcher/1"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return json.loads(r.read(2_000_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = e.read(400).decode("utf-8", "replace") if e.fp else ""
        raise RuntimeError(f"HTTP {e.code}: {redact(detail)[:200]}") from None


def _search(backend: str, query: str) -> list[dict]:
    if backend == "simulated":
        return [{"title": f"Simulated source {i} for {query[:40]}", "url": f"https://example.org/{i}",
                 "snippet": f"Synthetic finding {i} about {query[:60]}."} for i in (1, 2, 3)]
    key = _key(_KEY[backend])
    if backend == "firecrawl":
        d = _post(_ENDPOINT[backend], {"query": query, "limit": MAX_RESULTS, "sources": ["web"]}, key)
        if d.get("success") is False:
            raise RuntimeError(str(d.get("error") or "unsuccessful search")[:200])
        data = d.get("data")
        web = data.get("web") if isinstance(data, dict) else data if isinstance(data, list) else []
        return [{"title": w.get("title") or w.get("url"), "url": w.get("url"),
                 "snippet": w.get("description") or w.get("snippet") or (w.get("markdown") or "")[:300]}
                for w in (web or []) if isinstance(w, dict) and w.get("url")]
    d = _post(_ENDPOINT[backend], {"query": query, "max_results": MAX_RESULTS}, key)
    return [{"title": w.get("title") or w.get("url"), "url": w.get("url"), "snippet": w.get("snippet") or "",
             "date": w.get("date")} for w in d.get("results", []) if isinstance(w, dict) and w.get("url")]


def daily_used(store) -> int:
    row = store.one("SELECT v FROM kv WHERE k=?", (f"research_calls:{time.strftime('%Y-%m-%d')}",))
    return int(row["v"]) if row else 0


def _bump(store) -> None:
    k = f"research_calls:{time.strftime('%Y-%m-%d')}"
    store.x("INSERT INTO kv(k,v) VALUES(?, '1') ON CONFLICT(k) DO UPDATE SET v=CAST(v AS INTEGER)+1", (k,))


def research(store, query: str) -> dict:
    """One bounded public search. Returns {ok, backend, query, results, latency_s, error}."""
    query = redact(re.sub(r"\s+", " ", query or "").strip())[:MAX_QUERY]
    t0 = time.time()
    if not query:
        return {"ok": False, "query": query, "results": [], "error": "empty query", "latency_s": 0}
    if daily_used(store) >= DAILY_CAP:
        return {"ok": False, "query": query, "results": [], "error": f"daily research cap ({DAILY_CAP}) reached",
                "latency_s": 0}
    errors = []
    for b in backends():
        try:
            _bump(store)
            res = _search(b, query)[:MAX_RESULTS]
            out = {"ok": True, "backend": b, "query": query, "results": res, "latency_s": round(time.time() - t0, 2)}
            store.event("research_call", None, backend=b, results=len(res), latency_s=out["latency_s"])
            return out
        except (OSError, RuntimeError, ValueError) as e:
            errors.append(f"{DISPLAY.get(b, b)}: {type(e).__name__}: {redact(str(e))[:160]}")
    err = "; ".join(errors) or status()["note"]
    store.event("research_call", None, backend=None, ok=False)
    return {"ok": False, "query": query, "results": [], "error": err, "latency_s": round(time.time() - t0, 2)}


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
