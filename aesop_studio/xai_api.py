"""Metered xAI (Grok) Responses API route: the "regular" Grok with photos, through api.x.ai.

Same contract as openai_api (reserve a maximum cost, stream, settle from real usage). The key comes from the
XAI_API_KEY environment variable or the owner's DPAPI-protected xai.dpapi secret; it is resolved at call time,
sent only to api.x.ai and never stored, logged or returned. Prices below were read from api.x.ai
/v1/language-models on 2026-10-28 (USD per 1M tokens: prompt text, completion); image tokens bill at the
prompt-text rate on every listed model, and every listed model accepts text + image input.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from . import openai_api
from .openai_api import ApiError  # noqa: F401 - one error type for every metered route

PRICE_SOURCE = "api.x.ai /v1/language-models (live catalog), read 2026-10-28"
PRICES = {
    "grok-4.7": (2.00, 6.00),
    "grok-4.6": (2.00, 6.00),
    "grok-4.5": (2.00, 6.00),
    "grok-4.3": (1.25, 2.50),
}
DEFAULT_MODEL = "grok-4.7"
REASONING_EFFORT = None  # xAI selects reasoning per model; the Responses body carries no effort field
DEFAULT_MAX_OUTPUT = openai_api.DEFAULT_MAX_OUTPUT
MAX_OUTPUT_CAP = openai_api.MAX_OUTPUT_CAP
MAX_PROMPT_BYTES = openai_api.MAX_PROMPT_BYTES
API_HOST = "api.x.ai"


def _dpapi_path() -> Path:
    return Path(os.environ.get("AESOP_XAI_KEY_FILE") or
                Path.home() / ".codex" / "provider-mcp-secrets" / "xai.dpapi")


def key_source() -> str | None:
    if os.environ.get("XAI_API_KEY"):
        return "environment variable XAI_API_KEY"
    if os.name == "nt" and _dpapi_path().is_file():
        return f"DPAPI-protected file {_dpapi_path().name} (owner provider secret store)"
    return None


def key_present() -> bool:
    return key_source() is not None


def resolve_key() -> str:
    """Resolve the xAI key immediately before sending. Never logged, stored or returned in any output."""
    key = os.environ.get("XAI_API_KEY", "")
    if not key and os.name == "nt" and _dpapi_path().is_file():
        try:
            key = openai_api._dpapi_decrypt(_dpapi_path().read_bytes()).decode("ascii", "strict").strip()
        except (UnicodeDecodeError, OSError, ApiError) as e:
            raise ApiError("Grok API key is not configured (stored secret unreadable)") from e
    if not key or any(c.isspace() for c in key):
        raise ApiError("Grok API key is not configured")
    return key


def max_cost(model: str, prompt_bytes: int, max_output: int) -> float:
    return openai_api.max_cost(model, prompt_bytes, max_output, prices=PRICES)


def actual_cost(model: str, usage: dict) -> float:
    return openai_api.actual_cost(model, usage, prices=PRICES)


def stream(prompt: str, model: str, max_output: int, on_delta, cancel: threading.Event, timeout: int = 300,
           key: str | None = None, images: list[str] | None = None) -> dict:
    return openai_api.stream(prompt, model, max_output, on_delta, cancel, timeout, key=key or resolve_key(),
                             images=images, host=API_HOST, reasoning_effort=REASONING_EFFORT)
