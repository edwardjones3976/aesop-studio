"""Drives the OWNER'S own Chrome over the DevTools port (one JSON command per stdin line, one JSON reply per line).

Runs under the project's .venv Python (which has Playwright); the Studio server talks to it through
aesop_studio.browser. It attaches to the owner's running Chrome (their real profile, logins and extensions) and
drives one tab that Studio opened — the owner's other tabs are never touched. There is no separate or isolated
browser any more.

The owner may type anywhere (their own machine, their own Chrome); a provider driving the browser (type with
"agent": true) is refused on password fields and solves no CAPTCHAs.

Usage: python browser_worker.py --cdp http://127.0.0.1:9222
"""
from __future__ import annotations

import base64
import json
import sys
import time

NAV_TIMEOUT = 30_000
SETTLE_MS = 1200
MAX_TEXT = 40_000
FALLBACK_W, FALLBACK_H = 1366, 854


def main(cdp_url: str) -> None:
    from playwright.sync_api import sync_playwright
    out = sys.stdout

    def reply(obj):
        out.write(json.dumps(obj) + "\n"); out.flush()

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(cdp_url, timeout=15_000)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        ctx.set_default_timeout(NAV_TIMEOUT)
        pages = [ctx.new_page()]  # Studio's own tab in the owner's Chrome
        ctx.on("page", lambda p: pages.append(p))

        def page():
            while len(pages) > 1 and pages[-1].is_closed():
                pages.pop()
            if pages[-1].is_closed():  # the owner closed Studio's tab in Chrome: open a fresh one
                pages[-1] = ctx.new_page()
            return pages[-1]

        def settle(p):
            try:
                p.wait_for_load_state("networkidle", timeout=SETTLE_MS)
            except Exception:
                p.wait_for_timeout(250)

        def dims(p):
            try:
                d = p.evaluate("() => ({w: window.innerWidth, h: window.innerHeight})")
                return int(d["w"]) or FALLBACK_W, int(d["h"]) or FALLBACK_H
            except Exception:
                return FALLBACK_W, FALLBACK_H

        def info():
            p = page()
            try:
                return {"url": p.url, "title": p.title()}
            except Exception:
                return {"url": getattr(p, "url", ""), "title": ""}

        try:
            page().bring_to_front()
        except Exception:
            pass
        reply({"ok": True, "ready": True})

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                cmd = json.loads(line)
            except ValueError:
                reply({"ok": False, "error": "bad command"}); continue
            op = cmd.get("op")
            p = page()
            try:
                if op == "ping":
                    reply({"ok": True, **info()})
                elif op == "navigate":
                    url = str(cmd.get("url") or "").strip()
                    if not url:
                        reply({"ok": False, "error": "no url"}); continue
                    if "://" not in url:
                        url = "https://" + url
                    if not url.lower().startswith(("http://", "https://")):
                        reply({"ok": False, "error": "only http(s) pages are allowed"}); continue
                    p.goto(url, wait_until="domcontentloaded"); settle(p)
                    reply({"ok": True, **info()})
                elif op == "shot":
                    w, hgt = dims(p)
                    png = p.screenshot(full_page=bool(cmd.get("full")), type="png", timeout=NAV_TIMEOUT)
                    reply({"ok": True, "png": base64.b64encode(png).decode("ascii"), "vw": w, "vh": hgt, **info()})
                elif op == "click":
                    p.mouse.click(float(cmd["x"]), float(cmd["y"])); p.wait_for_timeout(500); settle(page())
                    reply({"ok": True, **info()})
                elif op == "scroll":
                    p.mouse.wheel(0, float(cmd.get("dy", 700))); p.wait_for_timeout(250)
                    reply({"ok": True, **info()})
                elif op == "type":
                    if cmd.get("agent"):
                        is_pw = p.evaluate("() => { const e = document.activeElement; return !!e && e.tagName === 'INPUT' && e.type === 'password'; }")
                        if is_pw:
                            reply({"ok": False, "error": "refused: a provider cannot type into a password field"}); continue
                    p.keyboard.type(str(cmd.get("text", ""))[:2000], delay=10)
                    reply({"ok": True, **info()})
                elif op == "key":
                    p.keyboard.press(str(cmd.get("key", "Enter"))[:40]); p.wait_for_timeout(500); settle(page())
                    reply({"ok": True, **info()})
                elif op in ("back", "forward", "reload"):
                    getattr(p, {"back": "go_back", "forward": "go_forward", "reload": "reload"}[op])(); settle(page())
                    reply({"ok": True, **info()})
                elif op == "text":
                    txt = p.evaluate("() => document.body ? document.body.innerText : ''")
                    reply({"ok": True, "text": (txt or "")[:MAX_TEXT], **info()})
                elif op == "links":
                    links = p.evaluate("""() => [...document.querySelectorAll('a[href]')].slice(0, 120)
                        .map(a => ({text: (a.innerText||'').trim().slice(0,80), href: a.href})).filter(l => l.text && l.href.startsWith('http'))""")
                    reply({"ok": True, "links": links, **info()})
                elif op == "close":
                    reply({"ok": True, "bye": True}); break
                else:
                    reply({"ok": False, "error": f"unknown op {op!r}"})
            except Exception as e:  # noqa: BLE001 - every command answers, never crashes the worker
                reply({"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}", **info()})
        try:  # leave the owner's Chrome running: close only the tab Studio opened
            pages[-1].close()
        except Exception:
            pass


if __name__ == "__main__":
    args = sys.argv[1:]
    try:
        main(args[args.index("--cdp") + 1] if "--cdp" in args else "http://127.0.0.1:9222")
    except Exception as e:  # noqa: BLE001
        sys.stdout.write(json.dumps({"ok": False, "fatal": f"{type(e).__name__}: {str(e)[:300]}"}) + "\n")
        sys.stdout.flush()
        time.sleep(0.1)
