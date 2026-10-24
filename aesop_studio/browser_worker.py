"""Headless Chromium worker driven over stdin/stdout (one JSON command per line, one JSON reply per line).

Runs under the project's .venv Python, which has Playwright + Chrome; the Studio server (a different interpreter)
talks to it through aesop_studio.browser. One persistent page in one context, so sign-ins and tabs survive across
commands within a session. Owner/provider actions only; it never types into a password field and never solves
CAPTCHAs. Loopback concerns do not apply here — this reaches the public web as the owner's Chrome would.
"""
from __future__ import annotations

import base64
import json
import sys
import time

VIEWPORT = {"width": 1280, "height": 800}
NAV_TIMEOUT = 30_000
MAX_TEXT = 40_000


def main() -> None:
    from playwright.sync_api import sync_playwright
    out = sys.stdout

    def reply(obj):
        out.write(json.dumps(obj) + "\n")
        out.flush()

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport=VIEWPORT, ignore_https_errors=False,
                                  user_agent=None, locale="en-US")
        ctx.set_default_timeout(NAV_TIMEOUT)
        page = ctx.new_page()
        reply({"ok": True, "ready": True})

        def info():
            try:
                return {"url": page.url, "title": page.title()}
            except Exception:
                return {"url": page.url, "title": ""}

        def shot(full=False):
            png = page.screenshot(full_page=full, type="png", timeout=NAV_TIMEOUT)
            return base64.b64encode(png).decode("ascii")

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                cmd = json.loads(line)
            except ValueError:
                reply({"ok": False, "error": "bad command"})
                continue
            op = cmd.get("op")
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
                    page.goto(url, wait_until="domcontentloaded")
                    reply({"ok": True, **info()})
                elif op == "shot":
                    reply({"ok": True, "png": shot(cmd.get("full")), "viewport": VIEWPORT, **info()})
                elif op == "click":
                    x, y = float(cmd["x"]), float(cmd["y"])
                    page.mouse.click(x, y)
                    page.wait_for_timeout(300)
                    reply({"ok": True, **info()})
                elif op == "scroll":
                    page.mouse.wheel(0, float(cmd.get("dy", 600)))
                    page.wait_for_timeout(150)
                    reply({"ok": True, **info()})
                elif op == "type":
                    # Never type into a password field (or any obscured input), even if asked.
                    is_pw = page.evaluate("() => { const e = document.activeElement; return !!e && e.tagName === 'INPUT' && (e.type === 'password'); }")
                    if is_pw:
                        reply({"ok": False, "error": "refused: the focused field is a password input"}); continue
                    page.keyboard.type(str(cmd.get("text", ""))[:2000], delay=12)
                    reply({"ok": True, **info()})
                elif op == "key":
                    page.keyboard.press(str(cmd.get("key", "Enter"))[:40])
                    page.wait_for_timeout(300)
                    reply({"ok": True, **info()})
                elif op in ("back", "forward", "reload"):
                    getattr(page, {"back": "go_back", "forward": "go_forward", "reload": "reload"}[op])()
                    reply({"ok": True, **info()})
                elif op == "text":
                    txt = page.evaluate("() => document.body ? document.body.innerText : ''")
                    reply({"ok": True, "text": (txt or "")[:MAX_TEXT], **info()})
                elif op == "links":
                    links = page.evaluate("""() => [...document.querySelectorAll('a[href]')].slice(0, 120)
                        .map(a => ({text: (a.innerText||'').trim().slice(0,80), href: a.href})).filter(l => l.text && l.href.startsWith('http'))""")
                    reply({"ok": True, "links": links, **info()})
                elif op == "close":
                    reply({"ok": True, "bye": True}); break
                else:
                    reply({"ok": False, "error": f"unknown op {op!r}"})
            except Exception as e:  # noqa: BLE001 - every command answers, never crashes the worker
                reply({"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}", **info()})
        try:
            ctx.close(); browser.close()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        sys.stdout.write(json.dumps({"ok": False, "fatal": f"{type(e).__name__}: {str(e)[:300]}"}) + "\n")
        sys.stdout.flush()
        time.sleep(0.1)
