"""Loopback-only client for Aesop's exact local Director profile.

The task supervisor owns timeout, cancellation, output redaction and result persistence. This client performs one
request, makes no retry, verifies the pinned role bytes, and never contacts a non-loopback address.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROFILE_PATH = HERE / "director_profile.json"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _profile() -> tuple[dict, str]:
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    role = profile["system"]
    if hashlib.sha256(role.encode()).hexdigest() != profile["role_sha256"]:
        raise ValueError("Director role profile digest mismatch")
    return profile, role


def _port(name: str, default: int) -> int:
    value = int(os.environ.get(name, default))
    if not 1 <= value <= 65535:
        raise ValueError(f"invalid {name}")
    return value


def _request(backend: str, model: str, prompt: str, profile: dict, role: str) -> str:
    budget = profile["context_tokens"] - profile["max_output_tokens"] - profile["input_overhead_tokens"]
    used = len(role.encode()) + len(prompt.encode())
    if used > budget:
        raise ValueError(f"input exceeds the local Director context contract ({used} > {budget} conservative tokens)")
    if backend == "lmstudio":
        url = f"http://127.0.0.1:{_port('AESOP_LMSTUDIO_PORT', 1234)}/v1/chat/completions"
        body = {"model": model, "messages": [{"role": "system", "content": role},
                {"role": "user", "content": prompt}], "temperature": profile["temperature"],
                "max_tokens": profile["max_output_tokens"], "stream": False}
    elif backend == "ollama":
        url = f"http://127.0.0.1:{_port('AESOP_OLLAMA_PORT', 11434)}/api/chat"
        body = {"model": model, "messages": [{"role": "system", "content": role},
                {"role": "user", "content": prompt}], "stream": False,
                "options": {"num_ctx": profile["context_tokens"], "num_predict": profile["max_output_tokens"],
                            "temperature": profile["temperature"]}}
    else:
        raise ValueError("unknown local Director backend")
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(req, timeout=600) as response:
        data = json.loads(response.read().decode("utf-8", "replace"))
    if data.get("model") != model:
        raise ValueError("local Director backend substituted the pinned model")
    if backend == "lmstudio":
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    else:
        text = (data.get("message") or {}).get("content") or ""
    return re.sub(r"<think>.*?(?:</think>\s*|\Z)", "", text, flags=re.S).strip()


def _configure_utf8_stdio() -> None:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    try:
        _configure_utf8_stdio()
        backend, model, out_file = sys.argv[1:4]
        profile, role = _profile()
        if model != profile["models"].get(backend):
            raise ValueError("local Director model does not match the pinned profile")
        text = _request(backend, model, sys.stdin.read(), profile, role)
        if not text:
            raise ValueError("local Director returned no text")
        print(text, flush=True)
        Path(out_file).write_text(text, encoding="utf-8")
        return 0
    except Exception as exc:  # noqa: BLE001 - a bounded, redacted task failure is the public contract
        print(f"local Director error: {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
