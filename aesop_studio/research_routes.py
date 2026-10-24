"""Perplexity and Firecrawl as chat providers: ask them on the spot, like their own apps.

- Firecrawl (plan credits): a question runs a web search and returns the sources with their excerpts; a message
  that contains URLs reads those pages instead (clean page text, like Firecrawl's playground).
- Perplexity (metered, Sonar API): a question gets an answer with numbered citations, using the recent
  conversation for context. Billed per call under the active spend envelope with a bounded reservation.

Keys come from the process or Windows user environment (FIRECRAWL_API_KEY, PERPLEXITY_API_KEY) and are never
logged. Only the user's question (Firecrawl) or the recent conversation (Perplexity) leaves the machine.
"""
from __future__ import annotations

import re
import time

from . import researcher
from .security import redact

URL_RE = re.compile(r"https?://[^\s<>()\"']+[^\s<>()\"'.,;:!?]")
MAX_PAGES = 3
PAGE_CHARS = 12_000
PPLX_MODEL = "sonar"
# Sonar (2026-10): $1 / 1M input + $1 / 1M output tokens, plus a $5-$12 per 1K request fee by search context size.
PPLX_RESERVE_USD = 0.03
PPLX_PRICE_NOTE = "Perplexity Sonar: $1/M tokens in+out + per-request fee (docs.perplexity.ai/getting-started/pricing)"
PPLX_MAX_TOKENS = 1200


PLACEHOLDER_RE = re.compile(r"your[-_ ]?(new[-_ ]?)?key|key[-_ ]?here|<key>|xxxx|example", re.I)
_REJECTED: dict[str, str] = {}  # route -> fingerprint of the key the provider refused (until the key changes)


def key(route_id: str) -> str:
    v = researcher._key({"firecrawl": "FIRECRAWL_API_KEY", "perplexity": "PERPLEXITY_API_KEY"}[route_id]).strip().strip("'\"")
    return "" if PLACEHOLDER_RE.search(v) else v


def _fp(v: str) -> str:
    import hashlib
    return hashlib.sha256(v.encode("utf-8")).hexdigest()[:16]


def key_problem(route_id: str) -> str | None:
    """Why the key cannot be used, in plain words (never the value)."""
    raw = researcher._key({"firecrawl": "FIRECRAWL_API_KEY", "perplexity": "PERPLEXITY_API_KEY"}[route_id]).strip()
    name = "FIRECRAWL_API_KEY" if route_id == "firecrawl" else "PERPLEXITY_API_KEY"
    if not raw:
        return f"Set {name} in your Windows user environment to enable"
    if PLACEHOLDER_RE.search(raw):
        return f"{name} holds the example text from the instructions, not a real key; set it again with your key"
    if _REJECTED.get(route_id) == _fp(key(route_id)):
        return f"The provider rejected this key (invalid or inactive); set a valid {name}"
    return None


def mark_rejected(route_id: str) -> None:
    k = key(route_id)
    if k:
        _REJECTED[route_id] = _fp(k)


def _clean_page(md: str) -> str:
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md or "")             # images
    lines = []
    for line in md.splitlines():
        bare = re.sub(r"\[([^\]]*)\]\([^)]*\)", "", line).strip(" -*|#>")
        if line.strip() and not bare and "](" in line:               # a menu line made only of links
            continue
        lines.append(re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line))   # keep link text, drop the URL
    md = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return md.strip()


def firecrawl(question: str) -> dict:
    """Returns {"text": markdown answer, "credits": estimate}."""
    k = key("firecrawl")
    urls = list(dict.fromkeys(URL_RE.findall(question)))[:MAX_PAGES]
    if urls:
        parts = []
        for u in urls:
            d = researcher._post("https://api.firecrawl.dev/v2/scrape",
                                 {"url": u, "formats": ["markdown"], "onlyMainContent": True}, k)
            data = d.get("data") or {}
            meta = data.get("metadata") or {}
            body = _clean_page(data.get("markdown") or "")
            clipped = body[:PAGE_CHARS] + ("\n\n…(page clipped)" if len(body) > PAGE_CHARS else "")
            parts.append(f"## {meta.get('title') or u}\n{u}\n\n{redact(clipped) or '(no readable text on this page)'}")
        return {"text": "\n\n---\n\n".join(parts), "credits": len(urls)}
    q = " ".join(question.split())[:researcher.MAX_QUERY]
    res = researcher._search("firecrawl", q)
    if not res:
        return {"text": f"Firecrawl found no web results for: {q}", "credits": 2}
    out = {"ok": True, "backend": "firecrawl", "query": q, "results": res}
    text = researcher.render(out, "you").replace("**Research for you:** ", "**Search:** ", 1)
    return {"text": text + "\n\n_Tip: include a URL in your message to have Firecrawl read that page._", "credits": 2}


def perplexity(messages: list[dict]) -> dict:
    """messages: [{"role": "user"|"assistant", "content": str}], newest last. Returns text, cost, usage."""
    k = key("perplexity")
    body = {"model": PPLX_MODEL, "messages": [{"role": "system", "content": "Be precise and concise. Cite sources."}]
            + messages, "max_tokens": PPLX_MAX_TOKENS}
    d = researcher._post("https://api.perplexity.ai/chat/completions", body, k)
    msg = ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    cites = d.get("citations") or [r.get("url") for r in (d.get("search_results") or []) if r.get("url")]
    if cites:
        msg += "\n\nSources:\n" + "\n".join(f"[{i}] {u}" for i, u in enumerate(cites, 1))
    usage = d.get("usage") or {}
    cost = None
    c = usage.get("cost")
    if isinstance(c, dict) and isinstance(c.get("total_cost"), (int, float)):
        cost = float(c["total_cost"])
    elif usage.get("total_tokens"):
        cost = round(usage["total_tokens"] / 1e6 * 1.0 + 0.012, 6)  # tokens + highest request fee: an upper estimate
    return {"text": redact(msg), "cost_usd": cost, "usage": {"input_tokens": usage.get("prompt_tokens"),
                                                              "output_tokens": usage.get("completion_tokens")}}


def perplexity_messages(history: list[dict], question: str) -> list[dict]:
    """Recent turns (alternating, as Sonar requires) plus the new question."""
    msgs: list[dict] = []
    for h in history[-6:]:
        role = "assistant" if h["role"] == "assistant" else "user"
        text = str(h["content"] or "")[:3000]
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"] += "\n\n" + text
        else:
            msgs.append({"role": role, "content": text})
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    if msgs and msgs[-1]["role"] == "user":
        msgs[-1]["content"] += "\n\n" + question
    else:
        msgs.append({"role": "user", "content": question})
    return msgs


def status() -> dict:
    return {rid: key_problem(rid) is None for rid in ("firecrawl", "perplexity")}


def run(route_id: str, payload: dict) -> dict:
    t0 = time.time()
    if route_id == "firecrawl":
        out = firecrawl(payload["question"])
    else:
        out = perplexity(payload["messages"])
    out["latency_s"] = round(time.time() - t0, 2)
    return out
