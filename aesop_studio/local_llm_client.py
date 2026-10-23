"""Tiny CLI client for a local OpenAI-compatible model server (LM Studio) on loopback.

Run by the task supervisor like any provider CLI, so it inherits timeouts, cancel, redaction and sandboxing.
Reads the prompt from stdin, writes the answer to stdout and to the out-file. Only 127.0.0.1 is ever contacted.
usage: python -I local_llm_client.py <model> <out_file>
"""
import json
import os
import re
import sys
import urllib.request

BASE = "http://127.0.0.1:%d/v1/chat/completions" % int(os.environ.get("AESOP_LMSTUDIO_PORT", "1234"))


def main() -> int:
    model, out_file = sys.argv[1], sys.argv[2]
    prompt = sys.stdin.read()
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3,
                       "max_tokens": 1200, "stream": False}).encode("utf-8")
    req = urllib.request.Request(BASE, data=body, headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # loopback only, never via a proxy
    try:
        with opener.open(req, timeout=600) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001 - reported to the supervisor as a failed turn
        print(f"local model error: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
        return 2
    text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.S).strip()  # drop hidden reasoning blocks
    if not text:
        print("local model returned no text", file=sys.stderr)
        return 3
    print(text, flush=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
