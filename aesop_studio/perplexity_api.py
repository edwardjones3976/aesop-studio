"""Perplexity Orchestrator: stdlib HTTP, tier-aware catalog and bounded streaming.

Pricing checked 2026-10-26: https://docs.perplexity.ai/docs/getting-started/pricing
Rates (USD / 1M tokens) come from the authenticated catalog, never invented slugs.
"""
from __future__ import annotations

import email.utils
import hashlib
import json
import math
import threading
import time
import urllib.error
import urllib.request

from . import openai_api, research_routes

ApiError = openai_api.ApiError
BASE_URL = "https://api.perplexity.ai/orchestrator/v1"
PRICE_SOURCE = "docs.perplexity.ai/docs/getting-started/pricing; catalog USD/1M rates, checked 2026-10-26"
DEFAULT_MAX_OUTPUT = openai_api.DEFAULT_MAX_OUTPUT
CATALOG_TTL = 300
_catalog = {}
_catalog_lock = threading.Lock()


def key_present() -> bool:
    return bool(research_routes.key("perplexity"))


def resolve_key() -> str:
    key = research_routes.key("perplexity")
    if not key or any(c.isspace() for c in key):
        raise ApiError("PERPLEXITY_API_KEY is not configured")
    return key


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # bearer credentials must stay on the original endpoint


def _urlopen(req, timeout):
    return urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout)


def retry_after(value: str | None) -> float:
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        try:
            seconds = email.utils.parsedate_to_datetime(value).timestamp() - time.time()
        except (ValueError, TypeError, OverflowError):
            seconds = 1.0
    return max(0.0, seconds) if math.isfinite(seconds) else 1.0


def response(req, timeout=45, cancel=None, on_attempt=None):
    """One recovery only for an explicit, unbilled 429; never replay an ambiguous send."""
    cancel = cancel if cancel is not None else threading.Event()
    deadline = time.monotonic() + timeout
    for attempt in range(2):
        if cancel.is_set():
            raise ApiError("request cancelled before send")
        if on_attempt:
            on_attempt()
        try:
            return _urlopen(req, timeout=max(0.01, deadline - time.monotonic()))
        except urllib.error.HTTPError as e:
            code = e.code
            delay = retry_after(e.headers.get("Retry-After"))
            e.close()
            if code == 429 and attempt == 0 and delay < deadline - time.monotonic():
                if not cancel.wait(delay):
                    continue
            note = {400: "model or request not in the catalog", 402: "usage tier excludes this model",
                    429: "rate limited; retry after the provider interval"}.get(code, "request rejected")
            raise ApiError(f"HTTP {code}: {note}") from None
    raise ApiError("request unavailable")


def catalog(refresh=False) -> list[dict]:
    key = resolve_key()
    fingerprint = hashlib.sha256(key.encode()).digest()
    with _catalog_lock:
        old = _catalog.get(fingerprint)
        if old and not refresh and time.monotonic() - old[0] < CATALOG_TTL:
            return old[1]
        req = urllib.request.Request(BASE_URL + "/models", headers={"Authorization": f"Bearer {key}"})
        try:
            with response(req) as r:
                data = json.loads(r.read(2_000_000))
            rows = data["data"]
            if not isinstance(rows, list):
                raise ValueError("invalid catalog")
            models = []
            for row in rows:
                rates = row.get("pricing") or {}
                if not isinstance(row.get("id"), str) or "/" not in row["id"]:
                    raise ValueError("invalid model id")
                if rates.get("unit") != "usd_per_1m_tokens":
                    continue  # unknown prices cannot support a bounded reservation
                values = [rates.get(k, rates.get("input")) for k in ("input", "output", "cache_read", "cache_write")]
                if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0
                       for v in values):
                    continue
                models.append({"id": row["id"], "pricing": dict(zip(
                    ("input", "output", "cache_read", "cache_write"), values))})
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            raise ApiError(f"catalog unavailable: {type(e).__name__}") from None
        _catalog.clear()  # a changed key must never inherit another key's catalog
        _catalog[fingerprint] = (time.monotonic(), models)
        return models


def prices(model: str) -> dict:
    for row in catalog():
        if row["id"] == model:
            return row["pricing"].copy()
    raise ApiError("choose a model from the current Perplexity Orchestrator catalog in Settings")


def max_cost(model, prompt_bytes, max_output, rates):
    if prompt_bytes > openai_api.MAX_PROMPT_BYTES or not 1 <= max_output <= openai_api.MAX_OUTPUT_CAP:
        raise ApiError("context or output exceeds the metered route cap")
    # Cache writes can cost more than fresh input. Reserve at the highest input rate.
    pin = max(rates[k] for k in ("input", "cache_read", "cache_write"))
    cost = ((prompt_bytes + 64) * pin + max_output * rates["output"]) / 1e6 * openai_api.SAFETY_MARGIN
    return max(0.0001, math.ceil(cost * 10000) / 10000)


def actual_cost(model, usage, rates):
    fresh, output = usage["prompt_tokens"], usage["completion_tokens"]
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    if any(type(v) is not int or v < 0 for v in (fresh, output, cached)) or cached > fresh:
        raise ApiError("invalid usage; keep reservation unresolved")
    return round(((fresh - cached) * rates["input"] + cached * rates["cache_read"]
                  + output * rates["output"]) / 1e6, 6)


def stream(prompt, model, max_output, on_delta, cancel, timeout=300, key=None, images=None):
    if images:
        raise ApiError("Perplexity Orchestrator is a text-only Studio route")
    if cancel.is_set():
        return {"text": "", "usage": None, "status": "cancelled_presend"}
    req = urllib.request.Request(BASE_URL + "/chat/completions", method="POST",
        headers={"Authorization": f"Bearer {key or resolve_key()}", "Content-Type": "application/json",
                 "Accept": "text/event-stream"},
        data=json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                         "max_completion_tokens": max_output, "stream": True,
                         "stream_options": {"include_usage": True}}).encode())
    done, stopped = threading.Event(), threading.Event()
    box = {"text": [], "usage": None, "status": "incomplete", "error": None}

    def work():
        try:
            with response(req, timeout, cancel) as r:
                finish = None
                for raw in r:
                    if stopped.is_set() or cancel.is_set():
                        return
                    line = raw.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        if finish == "stop":
                            box["status"] = "completed"
                        break
                    ev = json.loads(data)
                    if ev.get("error"):
                        raise ApiError("Orchestrator stream error")
                    choices = ev.get("choices", [])
                    if len(choices) > 1:
                        raise ApiError("Orchestrator returned multiple choices")
                    if choices:
                        choice = choices[0]
                        delta = (choice.get("delta") or {}).get("content") or ""
                        box["text"].append(delta)
                        if not stopped.is_set():
                            on_delta(delta)
                        finish = choice.get("finish_reason") or finish
                    if ev.get("usage") is not None:
                        box["usage"] = ev["usage"]
        except ApiError as e:
            box["error"] = e
        except Exception as e:
            box["error"] = ApiError(f"Orchestrator stream interrupted: {type(e).__name__}")
        finally:
            done.set()

    deadline = time.monotonic() + timeout
    threading.Thread(target=work, daemon=True).start()
    while not done.wait(0.1):
        if cancel.is_set() or time.monotonic() >= deadline:
            stopped.set()
            return {"text": "".join(box["text"]), "usage": None,
                    "status": "cancelled" if cancel.is_set() else "deadline"}
    if cancel.is_set():
        return {"text": "".join(box["text"]), "usage": None, "status": "cancelled"}
    if box["error"]:
        raise box["error"]
    # A length cap or broken stream keeps its reservation even if a usage chunk arrived.
    return {"text": "".join(box["text"]), "usage": box["usage"] if box["status"] == "completed" else None,
            "status": box["status"]}
