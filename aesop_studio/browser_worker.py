"""Headless Chromium worker driven over stdin/stdout (one JSON command per line, one JSON reply per line).

Runs under the project's .venv Python, which has Playwright + Chrome; the Studio server (a different interpreter)
talks to it through aesop_studio.browser. Three modes:

  python browser_worker.py <profile_dir>               Studio's own persistent Chrome (its own profile; sign-ins
                                                        survive restarts), headless, rendered 1366x854 @2x.
  python browser_worker.py <profile_dir> --signin URL  a real headful window on that profile for the owner to sign
                                                        in by hand (CAPTCHA / 2FA work); exits when they close it.
  python browser_worker.py --cdp http://127.0.0.1:9222 connect to the OWNER'S already-running Chrome (their real
                                                        profile and logins); Studio drives its own tab there.

The owner may type anywhere (their own machine); a provider driving the browser (type with "agent": true) is
refused on password fields and solves no CAPTCHAs.
"""
from __future__ import annotations

import base64
import json
import sys
import time

VIEWPORT = {"width": 1366, "height": 854}
SCALE = 2
NAV_TIMEOUT = 30_000
SETTLE_MS = 1200
MAX_TEXT = 40_000
ARGS = ["--disable-blink-features=AutomationControlled", "--hide-scrollbars", "--no-first-run",
        "--no-default-browser-check"]


def _context(pw, profile_dir: str, headless: bool):
    kw = dict(user_data_dir=profile_dir, headless=headless, viewport=VIEWPORT, device_scale_factor=SCALE,
              locale="en-US", color_scheme="light", args=ARGS)
    try:
        return pw.chromium.launch_persistent_context(channel="chrome", **kw)
    except Exception:
        return pw.chromium.launch_persistent_context(**kw)


def _signin(profile_dir: str, url: str) -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = _context(pw, profile_dir, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            if url:
                page.goto(url if "://" in url else "https://" + url, wait_until="domcontentloaded")
        except Exception:
            pass
        while True:
            try:
                if not [p for p in ctx.pages if not p.is_closed()]:
                    break
            except Exception:
                break
            time.sleep(0.5)
        try:
            ctx.close()
        except Exception:
            pass


def _loop(pages, add_listener, own_close) -> None:
    """Shared command loop. `pages` is a live list of pages; `own_close` closes only what this worker owns."""
    out = sys.stdout

    def reply(obj):
        out.write(json.dumps(obj) + "\n"); out.flush()

    def page():
        while len(pages) > 1 and pages[-1].is_closed():
            pages.pop()
        return pages[-1]

    def settle(p):
        try:
            p.wait_for_load_state("networkidle", timeout=SETTLE_MS)
        except Exception:
            p.wait_for_timeout(250)

    def info():
        p = page()
        try:
            return {"url": p.url, "title": p.title()}
        except Exception:
            return {"url": getattr(p, "url", ""), "title": ""}

    def shot(full=False):
        return base64.b64encode(page().screenshot(full_page=full, type="png", timeout=NAV_TIMEOUT)).decode("ascii")

    reply({"ok": True, "ready": True, "viewport": VIEWPORT})
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
                p.bring_to_front(); p.goto(url, wait_until="domcontentloaded"); settle(p)
                reply({"ok": True, **info()})
            elif op == "shot":
                reply({"ok": True, "png": shot(cmd.get("full")), "viewport": VIEWPORT, "scale": SCALE, **info()})
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
    own_close()


def main_profile(profile_dir: str) -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = _context(pw, profile_dir, headless=True)
        ctx.set_default_timeout(NAV_TIMEOUT)
        pages = ctx.pages or [ctx.new_page()]
        _loop(pages, lambda f: ctx.on("page", f), lambda: _safe(ctx.close))


def main_cdp(cdp_url: str) -> None:
    """Attach to the owner's running Chrome and drive a fresh tab in it (their real profile and logins)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(cdp_url, timeout=15_000)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        ctx.set_default_timeout(NAV_TIMEOUT)
        page = ctx.new_page()  # Studio's own tab; the owner's other tabs are untouched
        pages = [page]
        try:
            page.bring_to_front()
        except Exception:
            pass
        # leave the owner's Chrome running on exit: close only Studio's tab, keep the CDP connection's browser alive
        _loop(pages, lambda f: ctx.on("page", f), lambda: _safe(page.close))


def _safe(fn):
    try:
        fn()
    except Exception:
        pass


if __name__ == "__main__":
    args = sys.argv[1:]
    try:
        if "--cdp" in args:
            main_cdp(args[args.index("--cdp") + 1])
        elif "--signin" in args:
            prof = args[0]
            _signin(prof, args[args.index("--signin") + 1] if args.index("--signin") + 1 < len(args) else "")
        else:
            main_profile(args[0] if args else ".browser-profile")
    except Exception as e:  # noqa: BLE001
        sys.stdout.write(json.dumps({"ok": False, "fatal": f"{type(e).__name__}: {str(e)[:300]}"}) + "\n")
        sys.stdout.flush()
        time.sleep(0.1)
