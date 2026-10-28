"""Metered OpenAI Responses API route with bounded, pre-reserved cost.

The key comes from the OPENAI_API_KEY environment variable or, failing that, the owner's
DPAPI-protected provider secret (decryptable only by this Windows user). It is resolved at
call time, sent only to api.openai.com, and never stored, logged or returned. Readiness
checks look at presence only and never decrypt. Every request is capped by
max_output_tokens, so its maximum cost is known before dispatch.
"""
from __future__ import annotations

import ctypes
import http.client
import json
import math
import socket
import time
import os
import threading
import urllib.parse
from pathlib import Path

# Standard-tier prices in USD per 1M tokens, verified 2026-10-23 from
# https://developers.openai.com/api/docs/pricing . Reasoning tokens bill as output.
PRICE_SOURCE = "developers.openai.com/api/docs/pricing (Standard tier), verified 2026-10-23"
PRICES = {
    "gpt-6-luna": (0.10, 0.50),
    "gpt-6.1-sol": (2.00, 10.00),
    "gpt-6-astra": (10.00, 50.00),
}
DEFAULT_MODEL = "gpt-6.1-sol"  # middle of luna / sol / astra on price, speed and capability
REASONING_EFFORT = "medium"
DEFAULT_MAX_OUTPUT = 2000
MAX_OUTPUT_CAP = 16000
SAFETY_MARGIN = 1.10
MAX_PROMPT_BYTES = 400_000  # bounds every reservation; larger contexts are refused, never silently truncated
API_HOST = "api.openai.com"


class ApiError(RuntimeError):
    pass


def _dpapi_path() -> Path:
    return Path(os.environ.get("AESOP_OPENAI_KEY_FILE") or
                Path.home() / ".codex" / "provider-mcp-secrets" / "openai.dpapi")


def key_source() -> str | None:
    if os.environ.get("OPENAI_API_KEY"):
        return "environment variable OPENAI_API_KEY"
    if os.name == "nt" and _dpapi_path().is_file():
        return f"DPAPI-protected file {_dpapi_path().name} (owner provider secret store)"
    return None


def key_present() -> bool:
    return key_source() is not None


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi_decrypt(data: bytes) -> bytes:
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in, blob_out = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), _Blob()
    if not crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise ApiError("could not decrypt the Codex API key for this Windows user")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _test_mode() -> bool:
    return bool(os.environ.get("AESOP_OPENAI_TEST_BASE")) and os.environ.get("AESOP_SIMULATED_ROUTE") == "1"


def resolve_key() -> str:
    """Resolve the key immediately before sending. Never logged, stored or returned in any output."""
    key = os.environ.get("OPENAI_API_KEY", "")
    if _test_mode():  # the local fake endpoint may only ever receive an obviously fake key
        if not key.startswith("test-"):
            raise ApiError("test endpoint override requires a test- key; real keys are refused")
        return key
    if not key and os.name == "nt" and _dpapi_path().is_file():
        try:
            key = _dpapi_decrypt(_dpapi_path().read_bytes()).decode("ascii", "strict").strip()
        except (UnicodeDecodeError, OSError) as e:
            raise ApiError("Codex API key is not configured (stored secret unreadable)") from e
    if not key or any(c.isspace() for c in key):
        raise ApiError("Codex API key is not configured")
    return key


def max_cost(model: str, prompt_bytes: int, max_output: int) -> float:
    """Conservative upper bound. A token is never shorter than one UTF-8 byte, so bytes bound input tokens
    for any script (CJK, emoji, dense code); plus the full output allowance and a 10% margin."""
    if model not in PRICES:
        raise ApiError(f"no verified price for {model}; metered dispatch refused")
    if prompt_bytes > MAX_PROMPT_BYTES:
        raise ApiError(f"context is {prompt_bytes:,} bytes; the metered route accepts at most {MAX_PROMPT_BYTES:,}")
    pin, pout = PRICES[model]
    in_tokens = prompt_bytes + 64
    cost = (in_tokens * pin + max_output * pout) / 1_000_000 * SAFETY_MARGIN
    return math.ceil(cost * 10000) / 10000  # round up to $0.0001


def actual_cost(model: str, usage: dict) -> float:
    pin, pout = PRICES[model]
    return round((usage.get("input_tokens", 0) * pin + usage.get("output_tokens", 0) * pout) / 1_000_000, 6)


def _endpoint() -> tuple[str, int, bool]:
    # Test-only override (local fake server); impossible to enable outside the offline test mode.
    base = os.environ.get("AESOP_OPENAI_TEST_BASE")
    if base and _test_mode():
        u = urllib.parse.urlsplit(base)
        if u.hostname in ("127.0.0.1", "localhost"):
            return u.hostname, u.port or 80, False
    return API_HOST, 443, True


IMAGE_TOKEN_BOUND = 3000  # conservative per-image input bound (high-detail tiles) used for reservations


def stream(prompt: str, model: str, max_output: int, on_delta, cancel: threading.Event, timeout: int = 300,
           key: str | None = None, images: list[str] | None = None) -> dict:
    """Stream a Responses API call. Returns {"text", "usage", "status"}; raises ApiError on failure.
    `images` are data: URLs (PNG/JPEG) sent alongside the text as one user message.

    Status values: completed/incomplete (usage known), cancelled_presend (nothing sent: $0), cancelled or deadline
    (request may have been billed: caller keeps the reservation as unresolved exposure).
    The HTTP exchange runs on a worker thread so cancel and the overall deadline return promptly on every
    platform (on Windows a blocked socket read cannot be interrupted from another thread)."""
    key = key or resolve_key()
    if cancel.is_set():  # nothing sent yet: the caller settles this at $0
        return {"text": "", "usage": None, "status": "cancelled_presend"}
    host, port, tls = _endpoint()
    payload = prompt if not images else [{"role": "user", "content": [{"type": "input_text", "text": prompt}] + [
        {"type": "input_image", "image_url": u, "detail": "high"} for u in images]}]
    body = json.dumps({"model": model, "input": payload, "max_output_tokens": max_output, "stream": True,
                       "store": False, "reasoning": {"effort": REASONING_EFFORT}})
    deadline = time.monotonic() + timeout
    stopped = threading.Event()      # set when the caller stops listening: later deltas are discarded
    done = threading.Event()
    box: dict = {"text": [], "usage": None, "status": "incomplete", "error": None}
    conn = (http.client.HTTPSConnection if tls else http.client.HTTPConnection)(host, port, timeout=timeout + 5)

    def work():
        try:
            conn.request("POST", "/v1/responses", body=body, headers={
                "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "text/event-stream"})
            resp = conn.getresponse()
            if resp.status != 200:
                detail = resp.read(4000).decode("utf-8", "replace")
                try:
                    detail = json.loads(detail)["error"]["message"]
                except (ValueError, KeyError, TypeError):
                    pass
                raise ApiError(f"HTTP {resp.status}: {detail}"[:500])
            for raw in resp:
                if stopped.is_set():
                    return
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    ev = json.loads(data)
                except ValueError:
                    continue
                if not isinstance(ev, dict):
                    continue
                t = ev.get("type", "")
                if t == "response.output_text.delta":
                    d = ev.get("delta", "")
                    box["text"].append(d)
                    if not stopped.is_set():
                        on_delta(d)
                elif t in ("response.completed", "response.incomplete", "response.failed"):
                    r = ev.get("response") or {}
                    box["usage"] = r.get("usage")
                    box["status"] = r.get("status") or t.split(".")[-1]
                    if t == "response.failed":
                        raise ApiError(f"response failed: {(r.get('error') or {}).get('message', 'unknown')}")
                    break
                elif t == "error":
                    raise ApiError(f"stream error: {ev.get('message') or ev}")
        except ApiError as e:
            box["error"] = e
        except (OSError, http.client.HTTPException) as e:
            box["error"] = ApiError(f"network error: {e}")
        except Exception as e:  # noqa: BLE001 - surfaced to the caller as a failure, never swallowed
            box["error"] = ApiError(f"unexpected client error: {type(e).__name__}")
        finally:
            try:
                conn.close()
            except OSError:
                pass
            done.set()

    threading.Thread(target=work, daemon=True).start()
    while not done.wait(0.2):
        if cancel.is_set() or time.monotonic() > deadline:
            stopped.set()
            try:  # best effort; the worker exits on its own when the socket finally errors or closes
                if conn.sock is not None:
                    conn.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            return {"text": "".join(box["text"]), "usage": None,
                    "status": "cancelled" if cancel.is_set() else "deadline"}
    if box["error"] is not None:
        raise box["error"]
    return {"text": "".join(box["text"]), "usage": box["usage"], "status": box["status"]}
