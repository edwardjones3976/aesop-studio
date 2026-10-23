"""Keyboard / accessibility / zoom QA for Aesop Studio (Playwright + installed Chrome, synthetic data).

Checks: Ctrl+K palette opens and Escape closes it with focus restored; Ctrl+1/2/3 switch workspaces
(not while typing); visible focus indicator; icon buttons have accessible names; 200% zoom
(CSS viewport halved) has no page-level horizontal overflow; reduced-motion emulation leaves no
long transitions; composer min/max height; pane width persistence across reload.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ui_qa import ROOT, free_port, seed, start_server  # noqa: E402


def main():
    tmp = Path(tempfile.mkdtemp(prefix="aesop-a11y-"))
    (tmp / "proj").mkdir()
    port = free_port()
    proc, link = start_server(ROOT, tmp / "data", port)
    res: dict = {}
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(channel="chrome", headless=True)
            ctx = b.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
            page = ctx.new_page()
            errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.goto(link)
            seed(page, "", tmp / "proj")
            page.goto(f"http://127.0.0.1:{port}/")
            page.wait_for_timeout(1500)

            # Ctrl+K palette and focus restore
            page.locator("body").click(position={"x": 5, "y": 5})
            page.keyboard.press("Tab")
            before = page.evaluate("() => document.activeElement && (document.activeElement.id || document.activeElement.textContent.trim().slice(0,30))")
            page.keyboard.press("Control+k")
            page.wait_for_timeout(400)
            opened = page.evaluate("""() => { const d = [...document.querySelectorAll('dialog[open], [role=dialog]')]
                .filter(e => e.offsetParent !== null || e.open); return d.length > 0 &&
                d.some(e => e.contains(document.activeElement)); }""")
            page.keyboard.type("evid")
            page.wait_for_timeout(200)
            options = page.evaluate("() => [...document.querySelectorAll('[role=option]')].filter(o => o.offsetParent).map(o => o.textContent.trim()).slice(0,5)")
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)
            after = page.evaluate("() => document.activeElement && (document.activeElement.id || document.activeElement.textContent.trim().slice(0,30))")
            still_open = page.evaluate("() => !!document.querySelector('dialog[open]')")
            res["palette"] = {"opened_with_focus_inside": opened, "filtered_options": options,
                              "closed_on_escape": not still_open, "focus_restored": before == after,
                              "focus_before": before, "focus_after": after}

            # Ctrl+1/2/3
            ws = {}
            for key, name in (("1", "chat"), ("2", "agent"), ("3", "research")):
                page.locator("body").click(position={"x": 5, "y": 5})
                page.keyboard.press(f"Control+{key}")
                page.wait_for_timeout(500)
                ws[key] = page.evaluate("(n) => document.querySelector(`[data-tab=${n}]`)?.getAttribute('aria-selected')", name)
            # Not while typing
            page.keyboard.press("Control+1")
            page.wait_for_timeout(400)
            ta = page.locator("textarea").first
            typing_guard = None
            if ta.count():
                ta.click()
                page.keyboard.press("Control+3")
                page.wait_for_timeout(300)
                typing_guard = page.evaluate("() => document.querySelector('[data-tab=chat]')?.getAttribute('aria-selected')") == "true"
            res["shortcuts"] = {"ctrl1_chat": ws["1"], "ctrl2_build": ws["2"], "ctrl3_research": ws["3"],
                                "ignored_while_typing": typing_guard}

            # Composer sizing
            if ta.count():
                h0 = ta.evaluate("e => e.getBoundingClientRect().height")
                ta.fill("line\n" * 60)
                page.wait_for_timeout(200)
                h1 = ta.evaluate("e => e.getBoundingClientRect().height")
                res["composer"] = {"min_px": round(h0), "max_after_60_lines_px": round(h1),
                                   "ok": h0 >= 95 and h1 <= 241}
                ta.fill("")

            # Focus visibility: tab through 15 stops, record outline/box-shadow presence
            page.locator("body").click(position={"x": 5, "y": 5})
            vis, names = [], []
            for _ in range(15):
                page.keyboard.press("Tab")
                vis.append(page.evaluate("""() => { const e = document.activeElement; if (!e || e === document.body) return null;
                    const s = getComputedStyle(e); return (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== 'none'; }"""))
            res["focus_visible"] = {"stops": len(vis), "visible": sum(1 for v in vis if v), "none": vis.count(None)}

            unnamed = page.evaluate("""() => [...document.querySelectorAll('button, [role=button], a[href], input, select, textarea')]
                .filter(e => e.offsetParent !== null)
                .filter(e => !(e.getAttribute('aria-label') || e.textContent.trim() || e.title || (e.labels && e.labels.length) || e.getAttribute('aria-labelledby') || e.placeholder))
                .map(e => e.outerHTML.slice(0, 80))""")
            res["unnamed_controls"] = unnamed

            small = page.evaluate("""() => [...document.querySelectorAll('button, input, select')].filter(e => e.offsetParent !== null)
                .map(e => [e.getAttribute('aria-label') || e.textContent.trim().slice(0,20) || e.tagName, Math.round(e.getBoundingClientRect().height)])
                .filter(([, h]) => h < 40)""")
            res["controls_under_40px_desktop"] = small

            # Pane persistence
            sep = page.locator("[role=separator]")
            res["separators"] = sep.count()
            if sep.count():
                s0 = sep.first
                s0.focus()
                v0 = s0.get_attribute("aria-valuenow")
                for _ in range(3):
                    page.keyboard.press("ArrowLeft")
                v1 = s0.get_attribute("aria-valuenow")
                page.reload()
                page.wait_for_timeout(1500)
                v2 = page.locator("[role=separator]").first.get_attribute("aria-valuenow")
                res["pane_resize"] = {"before": v0, "after_keys": v1, "after_reload": v2, "persisted": v1 == v2 and v0 != v1}

            # 200% zoom == half CSS viewport at the 1920x1080 and 1366x768 targets
            zoom = {}
            for w, h in ((960, 540), (683, 384)):
                page.set_viewport_size({"width": w, "height": h})
                page.wait_for_timeout(400)
                for n in ("chat", "agent", "research"):
                    page.evaluate("(n) => document.querySelector(`[data-tab=${n}]`)?.click()", n)
                    page.wait_for_timeout(400)
                    m = page.evaluate("() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]")
                    zoom[f"{w}x{h}-{n}"] = m[0] <= m[1] + 1
                page.screenshot(path=str(ROOT / "docs" / "qa" / "after" / f"zoom200-{w}x{h}.png"))
            res["zoom200_no_overflow"] = zoom

            # Reduced motion: longest transition among visible elements
            res["reduced_motion_max_transition_ms"] = page.evaluate("""() => Math.max(0, ...[...document.querySelectorAll('*')]
                .map(e => getComputedStyle(e).transitionDuration.split(',').map(s => parseFloat(s) * (s.includes('ms') ? 1 : 1000))).flat()
                .filter(x => !isNaN(x)))""")
            res["page_errors"] = errs
            b.close()
    finally:
        proc.kill()
    out = ROOT / "docs" / "qa" / "after" / "a11y.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
