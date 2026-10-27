"""Drives Chrome over the DevTools port as a fallback worker (one JSON command per stdin line, one JSON reply per line).

In Browser v2, the primary bridge is the Chrome Extension in extension/ running in the owner's normal Chrome profile.
This worker provides fallback compatibility with the same structural DOM/accessibility snapshot and action protocol.
The owner may type anywhere; a provider driving the browser ("agent": true) is refused on password fields, CAPTCHAs,
and purchase/payment triggers.

Usage: python browser_worker.py --cdp http://127.0.0.1:9222
"""
from __future__ import annotations

import base64
import json
import sys
import time

NAV_TIMEOUT = 30_000
SETTLE_MS = 800
MAX_TEXT = 40_000
FALLBACK_W, FALLBACK_H = 1366, 854

PAGE_HELPER_JS = """
(payload) => {
  const op = payload.op || 'snapshot';
  const isPasswordField = (el) => {
    if (!el || !el.tagName) return false;
    const type = String(el.type || '').toLowerCase();
    const ac = String(el.getAttribute('autocomplete') || '').toLowerCase();
    const name = String(el.name || el.id || el.placeholder || el.getAttribute('aria-label') || '').toLowerCase();
    return type === 'password' || ac.includes('password') || /\\b(password|passwd|passcode|pin)\\b/i.test(name);
  };
  const isPaymentField = (el) => {
    if (!el || !el.tagName) return false;
    const ac = String(el.getAttribute('autocomplete') || '').toLowerCase();
    const name = String(el.name || el.id || el.placeholder || el.getAttribute('aria-label') || '').toLowerCase();
    return ac.startsWith('cc-') || /\\b(card[_\\s-]?number|cvv|cvc|cc-number|cc-csc|credit[_\\s-]?card)\\b/i.test(name);
  };
  const isCaptchaNode = (el) => {
    if (!el || !el.tagName) return false;
    const blob = [el.id, el.className, el.getAttribute('title'), el.getAttribute('aria-label'), el.getAttribute('data-sitekey'), el.src]
      .filter(Boolean).join(' ').toLowerCase();
    return /\\b(captcha|recaptcha|hcaptcha|cf-turnstile|g-recaptcha)\\b/i.test(blob);
  };
  const isPurchaseTrigger = (el) => {
    if (!el || !el.tagName) return false;
    const txt = String(el.innerText || el.value || el.getAttribute('aria-label') || el.title || '').trim().toLowerCase();
    return /\\b(buy now|place your order|place order|complete purchase|pay now|confirm payment|submit order|one-click buy)\\b/i.test(txt);
  };
  const labelFor = (el) => {
    if (!el) return '';
    if (isPasswordField(el)) return '[password field]';
    const aria = el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder');
    if (aria && aria.trim()) return aria.trim().slice(0, 120);
    const txt = el.innerText || el.value || el.getAttribute('alt') || el.name || '';
    return String(txt).replace(/\\s+/g, ' ').trim().slice(0, 120);
  };
  const roleFor = (el) => {
    const r = el.getAttribute('role');
    if (r) return r.toLowerCase();
    const tag = el.tagName.toLowerCase();
    if (tag === 'a') return 'link';
    if (tag === 'button' || tag === 'summary') return 'button';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input') {
      const t = String(el.type || 'text').toLowerCase();
      if (['button', 'submit', 'reset'].includes(t)) return 'button';
      if (t === 'search') return 'searchbox';
      return 'textbox';
    }
    return tag;
  };
  const resolveAnchor = (node) => {
    if (!node) return null;
    if (node.tagName && node.tagName.toLowerCase() === 'a' && (node.href || (node.getAttribute && node.getAttribute('href')))) return node;
    if (node.closest) { const pa = node.closest('a[href]'); if (pa) return pa; }
    if (node.querySelector) { const ca = node.querySelector('a[href]'); if (ca) return ca; }
    return null;
  };
  const resolveHref = (node) => {
    const a = resolveAnchor(node) || node;
    if (!a) return '';
    const raw = String(a.href || (a.getAttribute && a.getAttribute('href')) || '').trim();
    if (!raw || /^(javascript:|mailto:|tel:|data:|vbscript:)/i.test(raw)) return '';
    if (/^https?:\\/\\//i.test(raw)) return raw;
    try {
      const resolved = new URL(raw, window.location.href).href;
      return /^https?:\\/\\//i.test(resolved) ? resolved : '';
    } catch (_e) { return ''; }
  };
  const collect = () => {
    const vw = window.innerWidth || 1366;
    const vh = window.innerHeight || 854;
    for (const old of document.querySelectorAll('[data-aesop-ref]')) {
      old.removeAttribute('data-aesop-ref');
    }
    const headings = [...document.querySelectorAll('h1, h2, h3, h4')].slice(0, 35).map(h => ({
      level: Number(h.tagName.slice(1)),
      text: String(h.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 160)
    })).filter(h => h.text);
    const sel = "a[href],button,input:not([type='hidden']),select,textarea,summary,[role='button'],[role='link'],[role='tab'],[role='searchbox']";
    const elements = [];
    let refSeq = 1;
    for (const el of document.querySelectorAll(sel)) {
      if (elements.length >= 85) break;
      const rect = el.getBoundingClientRect();
      if (rect.width < 3 || rect.height < 3) continue;
      const href = resolveHref(el);
      const label = labelFor(el);
      if (!label && !href && !['input', 'textarea', 'select'].includes(el.tagName.toLowerCase())) continue;
      const ref = refSeq++;
      el.setAttribute('data-aesop-ref', String(ref));
      elements.push({
        ref,
        role: roleFor(el),
        tag: el.tagName.toLowerCase(),
        type: String(el.type || '').toLowerCase(),
        label: label || href.slice(0, 80) || el.tagName.toLowerCase(),
        href: href.slice(0, 300),
        rect: {
          x: Math.round(rect.left + rect.width / 2),
          y: Math.round(rect.top + rect.height / 2),
          left: Math.round(rect.left),
          top: Math.round(rect.top),
          w: Math.round(rect.width),
          h: Math.round(rect.height),
        },
        is_password: isPasswordField(el),
        is_captcha: isCaptchaNode(el),
        is_purchase: isPurchaseTrigger(el) || isPaymentField(el),
      });
    }
    const forms = [...document.querySelectorAll('form')].slice(0, 12).map((f, idx) => ({
      index: idx + 1,
      name: String(f.getAttribute('aria-label') || f.name || f.id || `form-${idx + 1}`).slice(0, 80),
      fields: [...f.querySelectorAll("input:not([type='hidden']),select,textarea,button")].slice(0, 15).map(c => ({
        ref: Number(c.getAttribute('data-aesop-ref') || 0) || null,
        role: roleFor(c),
        type: isPasswordField(c) ? 'password' : String(c.type || '').toLowerCase(),
        label: labelFor(c),
        is_password: isPasswordField(c),
      }))
    }));
    const links = [...document.querySelectorAll('a[href]')].slice(0, 120).map(a => ({
      ref: Number(a.getAttribute('data-aesop-ref') || 0) || null,
      text: String(a.innerText || '').trim().slice(0, 80),
      href: a.href
    })).filter(l => l.text && l.href.startsWith('http'));
    const mainEl = document.querySelector("main, article, [role='main'], #readme, .markdown-body") || document.body;
    return {
      ok: true,
      url: window.location.href,
      title: document.title || '',
      vw,
      vh,
      headings,
      elements,
      forms,
      links,
      main_text: String((mainEl && mainEl.innerText) || '').slice(0, 24000),
      text: String((document.body && document.body.innerText) || '').slice(0, 40000),
    };
  };
  const guard = (el) => {
    if (!payload.agent || !el) return null;
    if (isPasswordField(el)) return 'refused: a provider cannot type into a password field';
    if (isCaptchaNode(el)) return 'refused: a provider cannot solve CAPTCHAs';
    if (isPurchaseTrigger(el) || isPaymentField(el)) return 'refused: a provider cannot make purchases or enter payment details';
    return null;
  };
  if (op === 'check_active') {
    const err = guard(document.activeElement);
    return { ok: !err, error: err || '' };
  }
  if (op === 'click_ref' || op === 'fill_ref') {
    let el = document.querySelector(`[data-aesop-ref="${CSS.escape(String(payload.ref))}"]`);
    if (!el) { collect(); el = document.querySelector(`[data-aesop-ref="${CSS.escape(String(payload.ref))}"]`); }
    if (!el) return { ok: false, error: `element ref #${payload.ref} not found`, ...collect() };
    const anchor = resolveAnchor(el);
    const targetEl = anchor || el;
    const err = guard(el) || (anchor ? guard(anchor) : null);
    if (err) return { ok: false, error: err, ...collect() };
    const preClickUrl = window.location.href;
    const targetHref = resolveHref(targetEl) || (payload.href && /^https?:\\/\\//i.test(String(payload.href)) ? String(payload.href) : '');
    targetEl.scrollIntoView({ block: 'center', inline: 'nearest' });
    targetEl.focus && targetEl.focus();
    if (op === 'click_ref') {
      targetEl.click();
      if (targetEl !== el && el.click) { try { el.click(); } catch (_e) {} }
      return { ...collect(), clicked_href: targetHref, pre_click_url: preClickUrl };
    } else if ('value' in el) {
      el.value = String(payload.text || '').slice(0, 2000);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      if (payload.submit && el.form) {
        const ferr = guard(el.form);
        if (ferr) return { ok: false, error: ferr, ...collect() };
        el.form.requestSubmit ? el.form.requestSubmit() : el.form.submit();
      }
    }
    return collect();
  }
  if (op === 'find') {
    const snap = collect();
    const q = String(payload.query || '').trim().toLowerCase();
    const lines = (snap.text || '').split(/\\r?\\n/);
    const matches = [];
    for (let i = 0; i < lines.length && matches.length < 25; i++) {
      if (q && lines[i].toLowerCase().includes(q)) matches.push({ line: i + 1, snippet: lines[i].trim().slice(0, 220) });
    }
    const element_matches = (snap.elements || []).filter(e => q && ((e.label || '').toLowerCase().includes(q) || (e.href || '').toLowerCase().includes(q))).slice(0, 20);
    return { ...snap, matches, element_matches };
  }
  return collect();
}
"""


def main(cdp_url: str) -> None:
    from playwright.sync_api import sync_playwright
    out = sys.stdout

    def reply(obj):
        out.write(json.dumps(obj) + "\n"); out.flush()

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(cdp_url, timeout=15_000)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        ctx.set_default_timeout(NAV_TIMEOUT)
        pages = [ctx.new_page()]
        ctx.on("page", lambda p: pages.append(p))

        def page():
            while len(pages) > 1 and pages[-1].is_closed():
                pages.pop()
            if pages[-1].is_closed():
                pages[-1] = ctx.new_page()
            return pages[-1]

        def settle(p):
            try:
                p.wait_for_load_state("domcontentloaded", timeout=SETTLE_MS)
            except Exception:
                p.wait_for_timeout(150)

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

        def tabs_list():
            res = []
            cur = page()
            for idx, pg in enumerate(pages):
                if pg.is_closed():
                    continue
                try:
                    res.append({"id": idx + 1, "title": pg.title(), "url": pg.url, "selected": pg == cur})
                except Exception:
                    pass
            return res

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
                    reply({"ok": True, **info(), "tabs": tabs_list()})
                elif op == "navigate":
                    url = str(cmd.get("url") or "").strip()
                    if not url:
                        reply({"ok": False, "error": "no url"}); continue
                    if "://" not in url:
                        url = "https://" + url
                    if not url.lower().startswith(("http://", "https://")):
                        reply({"ok": False, "error": "only http(s) pages are allowed"}); continue
                    p.goto(url, wait_until="domcontentloaded"); settle(p)
                    snap = p.evaluate(PAGE_HELPER_JS, {"op": "snapshot"})
                    reply({**snap, "ok": True, **info(), "tabs": tabs_list()})
                elif op == "shot":
                    w, hgt = dims(p)
                    png = p.screenshot(full_page=bool(cmd.get("full")), type="png", timeout=NAV_TIMEOUT)
                    reply({"ok": True, "png": base64.b64encode(png).decode("ascii"), "vw": w, "vh": hgt, **info()})
                elif op in ("snapshot", "click_ref", "fill_ref", "find"):
                    res = p.evaluate(PAGE_HELPER_JS, cmd)
                    if op in ("click_ref", "fill_ref"):
                        p.wait_for_timeout(150); settle(page())
                        if op == "click_ref" and res.get("ok", True) and res.get("clicked_href"):
                            cur_u = getattr(page(), "url", "") or ""
                            pre_u = res.get("pre_click_url") or ""
                            href_u = str(res.get("clicked_href") or "")
                            if cur_u == pre_u and href_u.startswith(("http://", "https://")) and href_u != pre_u:
                                page().goto(href_u, wait_until="domcontentloaded"); settle(page())
                        res2 = page().evaluate(PAGE_HELPER_JS, {"op": "snapshot"})
                        res = {**res2, "ok": res.get("ok", True), "error": res.get("error", "")}
                    reply({**res, "tabs": tabs_list()})
                elif op == "click":
                    p.mouse.click(float(cmd["x"]), float(cmd["y"])); p.wait_for_timeout(200); settle(page())
                    reply({"ok": True, **info()})
                elif op == "scroll":
                    p.mouse.wheel(0, float(cmd.get("dy", 700))); p.wait_for_timeout(120)
                    reply({"ok": True, **info()})
                elif op == "type":
                    if cmd.get("agent"):
                        chk = p.evaluate(PAGE_HELPER_JS, {"op": "check_active", "agent": True})
                        if not chk.get("ok"):
                            reply({"ok": False, "error": chk.get("error") or "refused: a provider cannot type into a password field"}); continue
                    p.keyboard.type(str(cmd.get("text", ""))[:2000], delay=5)
                    reply({"ok": True, **info()})
                elif op == "key":
                    p.keyboard.press(str(cmd.get("key", "Enter"))[:40]); p.wait_for_timeout(200); settle(page())
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
                elif op == "tabs":
                    reply({"ok": True, "tabs": tabs_list(), **info()})
                elif op == "new_tab":
                    url = str(cmd.get("url") or "https://example.com").strip()
                    if "://" not in url:
                        url = "https://" + url
                    if not url.lower().startswith(("http://", "https://")):
                        reply({"ok": False, "error": "only http(s) pages are allowed"}); continue
                    np = ctx.new_page()
                    pages.append(np)
                    np.goto(url, wait_until="domcontentloaded"); settle(np)
                    reply({"ok": True, "tabs": tabs_list(), **info()})
                elif op == "switch_tab":
                    idx = int(cmd.get("tab_id") or 1) - 1
                    live_pages = [pg for pg in pages if not pg.is_closed()]
                    if 0 <= idx < len(live_pages):
                        chosen = live_pages[idx]
                        pages.remove(chosen)
                        pages.append(chosen)
                        chosen.bring_to_front()
                    reply({"ok": True, "tabs": tabs_list(), **info()})
                elif op == "close":
                    reply({"ok": True, "bye": True}); break
                else:
                    reply({"ok": False, "error": f"unknown op {op!r}"})
            except Exception as e:  # noqa: BLE001
                reply({"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}", **info()})
        try:
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
