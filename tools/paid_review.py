"""Paid independent review through the metered Codex API, accounted in Studio's own mission ledger.

A different model family from the in-session reviewers looks at the code (or the real UI screenshots) through
one lens at a time. Every call is reserved before sending (bytes bound input; images use a fixed per-image
token bound), settled from the API's reported usage, and the mission permit is switched off again afterwards.

Usage: python tools/paid_review.py --lens stability|security|frontend|visual [--model gpt-6-astra]
"""
from __future__ import annotations

import argparse
import base64
import math
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from aesop_studio import ledger, openai_api  # noqa: E402
from aesop_studio.store import Store  # noqa: E402

LENSES = {
    "stability": (["aesop_studio/tasks.py", "aesop_studio/ledger.py", "aesop_studio/store.py", "aesop_studio/server.py",
                   "aesop_studio/services.py", "aesop_studio/backup.py", "aesop_studio/providers.py",
                   "aesop_studio/openai_api.py"],
                  "Review for STABILITY and CORRECTNESS on Windows: race conditions, deadlocks, thread/process leaks, "
                  "SQLite locking/WAL misuse, unhandled exceptions that leave state stuck, restart/reconcile gaps, "
                  "timeouts, resource exhaustion, data loss. Ignore style."),
    "security": (["aesop_studio/server.py", "aesop_studio/security.py", "aesop_studio/services.py",
                  "aesop_studio/tasks.py", "aesop_studio/providers.py", "aesop_studio/openai_api.py",
                  "aesop_studio/backup.py", "aesop_studio/roundtable.py", "aesop_studio/lanes.py"],
                 "Review for SECURITY of a loopback-only local web app that launches provider CLIs and holds an API "
                 "key: authn/CSRF/Origin/Host, path traversal, command/argument injection, SSRF, secret leakage "
                 "(logs, exports, browser), DoS by an authenticated page, privilege boundaries. Ignore style."),
    "frontend": (["static/app.js", "static/index.html"],
                 "Review this vanilla-JS single-page app for ROBUSTNESS and UX bugs: stale state after navigation, "
                 "polling leaks, race conditions between async renders, error handling gaps, focus/keyboard/a11y "
                 "defects, XSS sinks, memory leaks, broken flows. Ignore style preferences."),
    "visual": ([], "You are a senior product designer. Critique these real screenshots of a desktop-first dark "
                   "'Coal/Ember' AI workspace (tokens: canvas #0B111A, panel #141F2C, raised #243243, coral action "
                   "#FF916C, mint #80E1CB, focus #9BD7FF; layout: topbar, nav rail, project explorer, canvas, "
                   "inspector). Find concrete visual/UX defects: hierarchy, alignment, spacing rhythm, density, "
                   "contrast, truncation, empty states, consistency, mobile layout. For each: screenshot, location, "
                   "problem, specific CSS-level fix. Prioritize; max 25 items."),
}
SHOTS = ["after/1920x1080-chat.png", "after/1440x900-chat.png", "after/1366x768-agent.png",
         "after/1024x768-evidence.png", "after/768x1024-research.png", "after/390x844-chat.png",
         "after/360x780-agent.png", "after/1440x900-providers.png", "journey/4-api-answer-cost.png"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lens", required=True, choices=sorted(LENSES))
    ap.add_argument("--model", default="gpt-6-astra", choices=sorted(openai_api.PRICES))
    ap.add_argument("--max-output", type=int, default=12000)
    a = ap.parse_args()
    files, brief = LENSES[a.lens]
    text = (f"{brief}\n\nOutput Markdown. For each finding: severity (critical/high/medium/low), file:line (or "
            "screenshot + region), concrete failure scenario, minimal fix. Only report issues you can point to "
            "in the material. If unsure, say so instead of guessing.\n\n")
    for f in files:
        src = (ROOT / f).read_text(encoding="utf-8")
        numbered = "\n".join(f"{i + 1:4d}  {line}" for i, line in enumerate(src.splitlines()))
        text += f"\n===== FILE {f} =====\n{numbered}\n"
    images = []
    if a.lens == "visual":
        for s in SHOTS:
            p = ROOT / "docs" / "qa" / s
            if p.is_file():
                images.append("data:image/png;base64," + base64.b64encode(p.read_bytes()).decode())
                text += f"\n[image {len(images)}: {s}]"
    store = Store(Path(os.environ.get("LOCALAPPDATA", ".")) / "AesopStudio")
    pin, pout = openai_api.PRICES[a.model]
    reserve = openai_api.max_cost(a.model, len(text.encode("utf-8")), a.max_output)
    reserve = math.ceil((reserve + len(images) * openai_api.IMAGE_TOKEN_BOUND * pin / 1e6 * 1.1) * 10000) / 10000
    ledger.set_permit(store, True)
    try:
        lid = ledger.reserve(store, "openai", "openai-api", "metered", reserve, task_ref=f"paid-review:{a.lens}",
                             price_source=f"{a.model}: {openai_api.PRICE_SOURCE}", purpose="mission")
        print(f"reserved ${reserve:.4f} for {a.lens} review on {a.model} ({len(text):,} chars, {len(images)} images)")
        t0 = time.time()
        try:
            r = openai_api.stream(text, a.model, a.max_output, lambda d: None, threading.Event(), timeout=900,
                                  images=images or None)
        except openai_api.ApiError as e:
            ledger.settle(store, lid, 0 if str(e).startswith("HTTP 4") else None)
            raise SystemExit(f"review failed: {e}")
        cost = openai_api.actual_cost(a.model, r["usage"]) if r["usage"] else None
        ledger.settle(store, lid, cost)
    finally:
        ledger.set_permit(store, False)
    out = ROOT / "docs" / "reviews" / f"{a.lens}-{a.model}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    u = r["usage"] or {}
    out.write_text(f"# Paid {a.lens} review ({a.model})\n\n_Codex API, {time.strftime('%Y-%m-%d %H:%M')}; "
                   f"{u.get('input_tokens')} input / {u.get('output_tokens')} output tokens; cost "
                   f"${cost if cost is not None else 'unknown'}; status {r['status']}; "
                   f"{round(time.time() - t0, 1)}s. Findings are model output to be verified, not facts._\n\n"
                   + r["text"] + "\n", encoding="utf-8")
    print(f"-> {out}  cost ${cost}  ({r['status']})")


if __name__ == "__main__":
    main()
