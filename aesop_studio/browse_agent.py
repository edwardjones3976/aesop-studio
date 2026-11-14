"""DOM- and Accessibility-Tree-first browser agent — bounded, owner-started, visible, and stoppable.

Browser v2 replaces v1's slow screenshot-only vision loop with a structured DOM/Accessibility agent:
1. Each step reads a rich, redacted structural snapshot of the active tab (title, URL, open tabs, H1-H4 outline,
   numbered interactive elements `[#ref] role "label"`, forms, and clean main article text).
2. The provider proposes ONE structured JSON action (`navigate`, `click_ref`, `fill_ref`, `click`, `type`, `key`,
   `scroll`, `find`, `switch_tab`, `new_tab`, `read`, `cite_notebook`, or `done`).
3. Screenshots are used only as an automatic fallback when a page has no readable DOM structure and the route
   supports vision.
4. Safety is enforced deterministically: providers never type into password fields, never solve CAPTCHAs, and never
   make purchases or enter payment details. Every action is visible in the step log and stoppable at any time.
"""
from __future__ import annotations

import json
import re
import tempfile
import threading
import time
from pathlib import Path

from . import providers
from .security import redact, sanitize_url
from .store import new_id
from .tasks import TERMINAL

VISION_ROUTES = ("claude", "codex", "openai-api")
BROWSE_ROUTES = ("claude", "codex", "openai-api", "cursor", "antigravity", "copilot", "simulated")
MAX_STEPS_CAP = 15
STEP_TIMEOUT = 150
VW, VH = 1366, 854

_PASSWORD_RE = re.compile(r"\b(password|passwd|passcode)\b", re.I)
_CAPTCHA_RE = re.compile(r"\b(captcha|recaptcha|hcaptcha|cf-turnstile|g-recaptcha)\b", re.I)
_PURCHASE_RE = re.compile(
    r"\b(buy now|place your order|place order|complete purchase|pay now|confirm payment|submit order|one-click buy|"
    r"card[_\s-]?number|cvv|cvc|cc-number|cc-csc)\b",
    re.I,
)
_NOTEBOOK_GOAL_RE = re.compile(r"\b(notebook|cite|citation|finding|findings|summarize.*notebook)\b", re.I)


def format_snapshot_for_prompt(snap: dict, last_find: dict | None = None) -> str:
    """Format a structured DOM + Accessibility snapshot for the browsing provider."""
    lines = []
    url = sanitize_url(str(snap.get("url") or ""))
    title = redact(str(snap.get("title") or ""))
    lines.append(f"CURRENT PAGE: {title or '(untitled)'}")
    lines.append(f"URL: {url or 'about:blank'}")
    lines.append(f"VIEWPORT: {snap.get('vw', VW)}x{snap.get('vh', VH)} (scrollY={snap.get('scrollY', 0)}/{snap.get('docH', VH)})")

    tabs = snap.get("tabs") or []
    if tabs:
        tab_lines = [
            f"  - [tab {t.get('id')}] {'(ACTIVE) ' if t.get('selected') else ''}{redact(str(t.get('title') or ''))[:80]} — {sanitize_url(str(t.get('url') or ''))[:140]}"
            for t in tabs[:12]
        ]
        lines.append("OPEN TABS:\n" + "\n".join(tab_lines))

    headings = snap.get("headings") or []
    if headings:
        h_lines = [f"  {'#' * max(1, min(4, int(h.get('level', 1))))} {redact(str(h.get('text', ''))[:140])}" for h in headings[:20]]
        lines.append("OUTLINE (HEADINGS):\n" + "\n".join(h_lines))

    elements = snap.get("elements") or []
    if elements:
        el_lines = []
        for e in elements[:65]:
            ref = e.get("ref")
            role = e.get("role") or e.get("tag") or "item"
            lbl = redact(str(e.get("label") or "")[:100])
            href = sanitize_url(str(e.get("href") or ""))[:140] if e.get("href") else ""
            flags = []
            if e.get("is_password"):
                flags.append("PROTECTED:PASSWORD")
            if e.get("is_captcha"):
                flags.append("PROTECTED:CAPTCHA")
            if e.get("is_purchase"):
                flags.append("PROTECTED:PURCHASE")
            flag_str = f" [{' '.join(flags)}]" if flags else ""
            href_str = f" -> {href}" if href else ""
            el_lines.append(f"  [#{ref}] {role} \"{lbl}\"{href_str}{flag_str}")
        lines.append("INTERACTIVE ELEMENTS (use click_ref / fill_ref with ref number):\n" + "\n".join(el_lines))
    elif snap.get("links"):
        lk_lines = [
            f"  - \"{redact(str(lk.get('text', ''))[:80])}\" -> {sanitize_url(str(lk.get('href', '')))[:160]}"
            for lk in (snap.get("links") or [])[:40]
        ]
        lines.append("LINKS:\n" + "\n".join(lk_lines))

    forms = snap.get("forms") or []
    if forms:
        f_lines = []
        for f in forms[:8]:
            flds = ", ".join(
                f"[#{fld.get('ref')}] {fld.get('role')}:{fld.get('label')}"
                for fld in (f.get("fields") or [])[:10]
            )
            f_lines.append(f"  Form \"{redact(str(f.get('name', ''))[:60])}\": {flds}")
        lines.append("FORMS:\n" + "\n".join(f_lines))

    if last_find:
        q = redact(str(last_find.get("query") or ""))
        m_lines = [f"  line {m.get('line')}: {redact(str(m.get('snippet', ''))[:180])}" for m in (last_find.get("matches") or [])[:12]]
        em_lines = [f"  [#{e.get('ref')}] {e.get('role')} \"{redact(str(e.get('label', ''))[:80])}\"" for e in (last_find.get("element_matches") or [])[:10]]
        lines.append(
            f"SEARCH RESULTS FOR {q!r}:\n"
            + ("\n".join(m_lines + em_lines) if (m_lines or em_lines) else "  (no matches on this page)")
        )

    body_text = redact(str(snap.get("main_text") or snap.get("text") or "")[:6000])
    lines.append("PAGE TEXT (main content):\n" + (body_text or "(empty)"))
    return "\n\n".join(lines)


def cite_page_to_notebook(
    store,
    pid: str,
    url: str,
    title: str,
    page_text: str,
    claim: str,
    locator: str = "",
    limitation: str = "",
) -> dict:
    """Save the current browser page as a read source and record a cited finding in the project's Research Notebook."""
    clean_url = sanitize_url((url or "").strip() or "https://local.page/")
    clean_title = redact((title or clean_url).strip())[:300]
    clean_text = redact((page_text or "").strip())[:1500]
    clean_claim = redact((claim or "").strip())[:2000]
    clean_loc = redact((locator or title or clean_url).strip())[:300]
    clean_lim = redact((limitation or "").strip())[:1000]
    if not clean_claim:
        raise ValueError("claim or summary is required to cite into the notebook")

    publisher = re.sub(r"^www\.", "", re.sub(r"^https?://([^/?#]+).*$", r"\1", clean_url))[:120] or "browser"
    now = time.time()
    existing = store.one("SELECT id FROM sources WHERE project_id=? AND locator=? AND status='read'", (pid, clean_url))
    if existing:
        sid = existing["id"]
    else:
        sid = new_id("src")
        store.x(
            "INSERT INTO sources(id,project_id,kind,title,publisher,locator,retrieved_at,version,status,excerpt,"
            "private,created) VALUES(?,?,?,?,?,?,?,?,?,?,0,?)",
            (sid, pid, "public", clean_title, publisher, clean_url, now, "browser-v2", "read", clean_text, now),
        )
    fid = new_id("fnd")
    store.x(
        "INSERT INTO findings(id,project_id,claim,source_id,locator,status,limitation,created) VALUES(?,?,?,?,?,?,?,?)",
        (fid, pid, clean_claim, sid, clean_loc, "cited", clean_lim, now),
    )
    store.event("browser_cite", pid, source_id=sid, finding_id=fid)
    return {
        "source": store.one("SELECT * FROM sources WHERE id=?", (sid,)),
        "finding": store.one("SELECT * FROM findings WHERE id=?", (fid,)),
    }


class Drive:
    def __init__(self, store, sup, browser):
        self.store, self.sup, self.browser = store, sup, browser
        self.lock = threading.Lock()
        self.run: dict | None = None
        self.dims = (VW, VH)

    def vision_routes(self) -> list[str]:
        routes = providers.cached(self.store)
        usable = [r for r in BROWSE_ROUTES if r in routes and providers.usable(routes[r], "chat")]
        if usable:
            return usable
        return [r for r in VISION_ROUTES if r in routes and providers.usable(routes[r], "chat")]

    def status(self) -> dict:
        r = self.run
        vroutes = self.vision_routes()
        if not r:
            return {"active": False, "vision_routes": vroutes, "routes": vroutes}
        return {
            "active": r["state"] == "RUNNING",
            "state": r["state"],
            "provider": r["provider"],
            "goal": r["goal"],
            "steps": r["steps"],
            "answer": r.get("answer", ""),
            "cited": r.get("cited"),
            "max_steps": r["max_steps"],
            "vision_routes": vroutes,
            "routes": vroutes,
        }

    def start(self, project: dict, provider: str, goal: str, max_steps: int = 6) -> dict:
        goal = " ".join((goal or "").split())[:600]
        if len(goal) < 3:
            raise ValueError("say what the provider should do")
        allowed = self.vision_routes()
        if provider not in allowed:
            raise ValueError(
                f"{providers.display_name(provider)} can't see the page; pick "
                + (" or ".join(providers.display_name(r) for r in allowed) or "a vision provider")
            )
        with self.lock:
            if self.run and self.run["state"] == "RUNNING":
                raise ValueError("a provider is already browsing; stop it first")
            if not (project.get("transfer_policy") or {}).get(provider):
                raise ValueError(
                    f"sending page images to {providers.display_name(provider)} is off for this project; "
                    "allow it in the project settings first"
                )
            self.run = {
                "state": "RUNNING",
                "provider": provider,
                "goal": goal,
                "max_steps": max(1, min(MAX_STEPS_CAP, int(max_steps))),
                "steps": [],
                "answer": "",
                "cited": None,
                "last_find": None,
                "last_snap": {},
                "stop": threading.Event(),
                "project": project,
            }
        threading.Thread(target=self._loop, args=(self.run,), daemon=True).start()
        return self.status()

    def stop(self) -> dict:
        r = self.run
        if r:
            r["stop"].set()
            tid = r.get("current_tid")
            if tid:
                try:
                    self.sup.cancel(tid)
                except Exception:
                    pass
        return self.status()

    # ---- Safety checks before executing any agent action ----
    def _safety_refusal(self, act: dict, snap: dict | None = None) -> str | None:
        a = str(act.get("action") or "").lower()
        snap = snap or (self.run or {}).get("last_snap") or {}
        elements = snap.get("elements") or []
        ref = act.get("ref")
        target = None
        if ref is not None:
            try:
                rnum = int(ref)
                target = next((e for e in elements if int(e.get("ref") or 0) == rnum), None)
            except (TypeError, ValueError):
                target = None

        if target:
            if target.get("is_password") or str(target.get("type") or "").lower() == "password":
                return "refused: a provider cannot type into a password field"
            if target.get("is_captcha") or _CAPTCHA_RE.search(str(target.get("label") or "")):
                return "refused: a provider cannot solve CAPTCHAs"
            if target.get("is_purchase") or _PURCHASE_RE.search(str(target.get("label") or "")):
                return "refused: a provider cannot make purchases or enter payment details"

        raw_target_desc = " ".join(
            str(act.get(k) or "") for k in ("label", "selector", "target", "field")
        )
        if _PASSWORD_RE.search(raw_target_desc) and a in ("type", "fill_ref", "click", "click_ref"):
            return "refused: a provider cannot type into a password field"
        if _CAPTCHA_RE.search(raw_target_desc):
            return "refused: a provider cannot solve CAPTCHAs"
        if _PURCHASE_RE.search(raw_target_desc):
            return "refused: a provider cannot make purchases or enter payment details"

        if a in ("type", "fill_ref"):
            txt = str(act.get("text") or "")
            if _PURCHASE_RE.search(txt):
                return "refused: a provider cannot make purchases or enter payment details"
        if a == "click" and "x" in act and "y" in act:
            try:
                x, y = float(act["x"]), float(act["y"])
                for e in elements:
                    r = e.get("bbox") or e.get("rect") or {}
                    left, top, w, h = r.get("left", r.get("x", 0)), r.get("top", r.get("y", 0)), r.get("w", 0), r.get("h", 0)
                    if w > 0 and h > 0 and left <= x <= left + w and top <= y <= top + h:
                        if e.get("is_password"):
                            return "refused: a provider cannot type into a password field"
                        if e.get("is_captcha"):
                            return "refused: a provider cannot solve CAPTCHAs"
                        if e.get("is_purchase"):
                            return "refused: a provider cannot make purchases or enter payment details"
            except (TypeError, ValueError):
                pass
        return None

    def _get_snapshot(self) -> dict:
        if hasattr(self.browser, "snapshot"):
            snap = self.browser.snapshot()
        else:
            info = self.browser.cmd("text")
            links = self.browser.cmd("links").get("links", [])
            snap = {
                "ok": True,
                "url": info.get("url", ""),
                "title": info.get("title", ""),
                "vw": self.dims[0],
                "vh": self.dims[1],
                "headings": [],
                "elements": [
                    {"ref": i + 1, "role": "link", "tag": "a", "label": lk.get("text", ""), "href": lk.get("href", "")}
                    for i, lk in enumerate(links[:50])
                ],
                "forms": [],
                "links": links,
                "main_text": info.get("text", ""),
                "text": info.get("text", ""),
                "tabs": [],
            }
        self.dims = (int(snap.get("vw") or VW), int(snap.get("vh") or VH))
        return snap

    def _ask(self, run: dict, snap: dict, shot_path: str | None = None) -> dict:
        hist = "\n".join(
            f"{i + 1}. {s['action']} {s.get('detail', '')} — {s.get('thought', '')}".strip()
            for i, s in enumerate(run["steps"][-10:])
        )
        structured_page = format_snapshot_for_prompt(snap, run.get("last_find"))
        prompt = (
            "You are operating the owner's web browser in Aesop Studio to accomplish their goal using the structured "
            "DOM and Accessibility snapshot below.\n\n"
            f"GOAL: {run['goal']}\n\n"
            f"Steps so far ({len(run['steps'])}/{run['max_steps']}):\n{hist or '(none yet)'}\n\n"
            f"{structured_page}\n\n"
            "Decide the single next action. Prefer semantic DOM actions (`click_ref`, `fill_ref`, `navigate`, `find`, "
            "`cite_notebook`) over raw pixel coordinates. Reply with ONLY one JSON object, no prose:\n"
            '{"thought": "<one short sentence>", '
            '"action": "navigate|click_ref|fill_ref|find|scroll|click|type|key|switch_tab|new_tab|read|cite_notebook|done", '
            '"url": "<for navigate or new_tab>", '
            '"ref": <int element #ref for click_ref or fill_ref>, '
            '"text": "<for fill_ref or type>", '
            '"submit": <bool optional for fill_ref>, '
            '"query": "<search term for find>", '
            '"tab_id": <int for switch_tab>, '
            '"x": <int for click fallback>, "y": <int for click fallback>, '
            '"key": "<e.g. Enter>", "dy": <pixels for scroll>, '
            '"claim": "<for cite_notebook or done>", "locator": "<section/release/heading cited>", '
            '"cite": <bool optional for done: true to save summary to project notebook>, '
            '"answer": "<for done: clear summary of what you found>"}\n'
            "Rules: one action only; NEVER enter passwords, payment card details, make purchases, or solve CAPTCHAs "
            "— if the goal requires those, use action \"done\" and explain why. Use \"done\" as soon as the goal is met."
        )
        images = [shot_path] if shot_path else None
        tid = self.sup.create(
            run["project"], run["provider"], prompt, mode="chat", timeout=STEP_TIMEOUT, images=images
        )
        run["current_tid"] = tid
        end = time.time() + STEP_TIMEOUT + 30
        while time.time() < end:
            t = self.sup.final(tid)
            if t["state"] in TERMINAL and not json.loads(t["checkpoint"] or "{}").get("retried_as"):
                break
            if run["stop"].is_set():
                self.sup.cancel(tid)
                return {"action": "done", "answer": "stopped by owner"}
            time.sleep(0.25)
        t = self.sup.final(tid)
        if t["state"] != "COMPLETED":
            return {"action": "error", "detail": f"provider turn {t['state'].lower()}"}
        text = (json.loads(t["checkpoint"] or "{}").get("result") or self.sup.output(t["id"])[0]).strip()
        m = re.search(r"\{[\s\S]*\}", text)
        try:
            return json.loads(m.group(0)) if m else {"action": "error", "detail": "no JSON action returned"}
        except ValueError:
            return {"action": "error", "detail": "unreadable action"}

    def _do(self, act: dict, run: dict | None = None) -> str:
        snap = (run or {}).get("last_snap") or {}
        refusal = self._safety_refusal(act, snap)
        if refusal:
            return f"[{refusal}]"

        a = act.get("action")
        if a == "navigate":
            r = self.browser.cmd("navigate", url=str(act.get("url") or ""), agent=True)
            return redact(r.get("url") or r.get("error") or "")
        if a == "click_ref":
            ref = int(act.get("ref") or 0)
            r = self.browser.cmd("click_ref", ref=ref, agent=True)
            if not r.get("ok") and r.get("error"):
                return f"#{ref} [{redact(str(r.get('error')))}]"
            return f"#{ref}"
        if a == "fill_ref":
            ref = int(act.get("ref") or 0)
            txt = str(act.get("text") or "")[:400]
            sub = bool(act.get("submit"))
            r = self.browser.cmd("fill_ref", ref=ref, text=txt, submit=sub, agent=True)
            return f"#{ref}: {redact(txt[:60])}" + ("" if r.get("ok") else f" [{redact(str(r.get('error')))}]")
        if a == "click":
            w, hgt = self.dims
            x = max(0, min(w, int(act.get("x", w // 2))))
            y = max(0, min(hgt, int(act.get("y", hgt // 2))))
            self.browser.cmd("click", x=x, y=y)
            return f"({x},{y})"
        if a == "type":
            r = self.browser.cmd("type", text=str(act.get("text", ""))[:400], agent=True)
            return redact(str(act.get("text", ""))[:60]) + ("" if r.get("ok") else f" [{r.get('error')}]")
        if a == "key":
            self.browser.cmd("key", key=str(act.get("key", "Enter")))
            return str(act.get("key", "Enter"))
        if a == "scroll":
            direction = str(act.get("direction") or "").lower()
            dy = int(act.get("dy", -600 if direction == "up" else 600))
            self.browser.cmd("scroll", dy=dy)
            return str(dy)
        if a == "find":
            q = str(act.get("query") or act.get("text") or "").strip()[:120]
            r = self.browser.cmd("find", query=q)
            if run is not None:
                run["last_find"] = {
                    "query": q,
                    "matches": r.get("matches") or [],
                    "element_matches": r.get("element_matches") or [],
                }
            nm = len(r.get("matches") or [])
            ne = len(r.get("element_matches") or [])
            return f"{redact(q)!r} ({nm} text, {ne} elements)"
        if a == "switch_tab":
            tid = int(act.get("tab_id") or 1)
            self.browser.cmd("switch_tab", tab_id=tid)
            return f"tab {tid}"
        if a == "new_tab":
            u = str(act.get("url") or "https://example.com")
            r = self.browser.cmd("new_tab", url=u, agent=True)
            return redact(r.get("url") or u)
        if a == "cite_notebook":
            if run and run.get("project"):
                cur_snap = run.get("last_snap") or {}
                claim = str(act.get("claim") or act.get("text") or act.get("answer") or act.get("thought") or "")
                loc = str(act.get("locator") or cur_snap.get("title") or "")
                lim = str(act.get("limitation") or "")
                res = cite_page_to_notebook(
                    self.store,
                    run["project"]["id"],
                    cur_snap.get("url") or "",
                    cur_snap.get("title") or "",
                    cur_snap.get("main_text") or cur_snap.get("text") or "",
                    claim,
                    loc,
                    lim,
                )
                run["cited"] = res["finding"]["id"]
                return f"cited to notebook ({res['finding']['id']})"
            return "(cited)"
        if a == "read":
            return "(read the page)"
        return ""

    def _loop(self, run: dict):
        try:
            for _ in range(run["max_steps"]):
                if run["stop"].is_set():
                    run["answer"] = run.get("answer") or "Stopped by the owner."
                    break
                try:
                    snap = self._get_snapshot()
                    run["last_snap"] = snap
                except Exception as e:  # noqa: BLE001
                    run["steps"].append({"action": "error", "detail": f"browser: {type(e).__name__}"})
                    break

                # Use screenshot fallback only when DOM snapshot has no elements/text and provider is a vision route
                shot_path = None
                fd = None
                needs_vision = (
                    not (snap.get("elements") or [])
                    and len((snap.get("text") or "").strip()) < 20
                    and run["provider"] in VISION_ROUTES
                )
                if needs_vision:
                    try:
                        sh = self.browser.shot(False)
                        fd = Path(tempfile.gettempdir()) / f"aesop-drive-{run['provider']}-{len(run['steps'])}.png"
                        fd.write_bytes(sh["png"])
                        shot_path = str(fd)
                    except Exception:
                        shot_path = None

                try:
                    act = self._ask(run, snap, shot_path)
                finally:
                    if fd is not None:
                        try:
                            fd.unlink()
                        except OSError:
                            pass

                a = act.get("action")
                step = {
                    "action": a,
                    "thought": redact(str(act.get("thought", ""))[:200]),
                    "url": snap.get("url"),
                    "title": snap.get("title"),
                }
                if a == "done":
                    ans = redact(str(act.get("answer", "") or act.get("claim", "") or act.get("thought", "")))[:2000]
                    run["answer"] = ans
                    if (act.get("cite") or _NOTEBOOK_GOAL_RE.search(run.get("goal", ""))) and not run.get("cited"):
                        if ans and not ans.lower().startswith("stopped by"):
                            try:
                                cited = cite_page_to_notebook(
                                    self.store,
                                    run["project"]["id"],
                                    snap.get("url") or "",
                                    snap.get("title") or "",
                                    snap.get("main_text") or snap.get("text") or "",
                                    ans,
                                    str(act.get("locator") or snap.get("title") or "browser summary"),
                                    str(act.get("limitation") or ""),
                                )
                                run["cited"] = cited["finding"]["id"]
                                step["detail"] = f"cited to notebook ({cited['finding']['id']})"
                            except Exception:
                                pass
                    run["steps"].append(step)
                    break

                refusal = self._safety_refusal(act, snap)
                if refusal:
                    step["action"] = "error"
                    step["detail"] = refusal
                    run["steps"].append(step)
                    break

                if a == "error":
                    step["detail"] = redact(str(act.get("detail", "unclear action"))[:200])
                    run["steps"].append(step)
                    if sum(1 for s in run["steps"][-3:] if s["action"] == "error") >= 3:
                        break
                    continue

                valid_actions = (
                    "navigate",
                    "click_ref",
                    "fill_ref",
                    "click",
                    "type",
                    "key",
                    "scroll",
                    "find",
                    "switch_tab",
                    "new_tab",
                    "cite_notebook",
                    "read",
                )
                if a not in valid_actions:
                    step.update(action="error", detail=f"unknown action {a!r}")
                    run["steps"].append(step)
                    continue

                step["detail"] = self._do(act, run)
                run["steps"].append(step)
                self.store.event("browse_step", run["project"]["id"], provider=run["provider"], action=a)
            run["state"] = "DONE"
        except Exception as e:  # noqa: BLE001
            run["state"] = "FAILED"
            run["steps"].append({"action": "error", "detail": f"{type(e).__name__}"})
        finally:
            if run["state"] == "RUNNING":
                run["state"] = "DONE"
