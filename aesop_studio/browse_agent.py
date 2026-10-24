"""A provider drives the shared browser toward a goal — bounded, owner-started, visible, and stoppable.

The owner clicks "Let <provider> browse", names a goal, and sets a step budget. Each step: Studio screenshots the
page, the provider (a vision chat route) proposes ONE action as JSON, Studio runs it against the browser and records
it. It stops at the goal, the step budget, the owner's Stop, or repeated failures. The worker still refuses to type
into password fields and solves no CAPTCHAs; nothing here touches files. This is the first, conservative version of
providers interacting with the page; it grows only as the owner asks.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from . import providers
from .security import redact
from .tasks import TERMINAL

VISION_ROUTES = ("claude", "codex", "openai-api")  # routes verified to read a screenshot
MAX_STEPS_CAP = 15
STEP_TIMEOUT = 150
VW, VH = 1366, 854


class Drive:
    def __init__(self, store, sup, browser):
        self.store, self.sup, self.browser = store, sup, browser
        self.lock = threading.Lock()
        self.run: dict | None = None

    def vision_routes(self) -> list[str]:
        routes = providers.cached(self.store)
        return [r for r in VISION_ROUTES if r in routes and providers.usable(routes[r], "chat")]

    def status(self) -> dict:
        r = self.run
        if not r:
            return {"active": False, "vision_routes": self.vision_routes()}
        return {"active": r["state"] == "RUNNING", "state": r["state"], "provider": r["provider"],
                "goal": r["goal"], "steps": r["steps"], "answer": r.get("answer", ""),
                "max_steps": r["max_steps"], "vision_routes": self.vision_routes()}

    def start(self, project: dict, provider: str, goal: str, max_steps: int = 6) -> dict:
        goal = " ".join((goal or "").split())[:600]
        if len(goal) < 3:
            raise ValueError("say what the provider should do")
        if provider not in self.vision_routes():
            raise ValueError(f"{providers.display_name(provider)} can't see the page; pick "
                             + " or ".join(providers.display_name(r) for r in self.vision_routes()) or "a vision provider")
        with self.lock:
            if self.run and self.run["state"] == "RUNNING":
                raise ValueError("a provider is already browsing; stop it first")
            if not (project.get("transfer_policy") or {}).get(provider):
                raise ValueError(f"sending page images to {providers.display_name(provider)} is off for this project; "
                                 "allow it in the project settings first")
            self.run = {"state": "RUNNING", "provider": provider, "goal": goal,
                        "max_steps": max(1, min(MAX_STEPS_CAP, int(max_steps))), "steps": [], "answer": "",
                        "stop": threading.Event(), "project": project}
        threading.Thread(target=self._loop, args=(self.run,), daemon=True).start()
        return self.status()

    def stop(self) -> dict:
        r = self.run
        if r:
            r["stop"].set()
        return self.status()

    # ---- the loop ----
    def _ask(self, run, shot_path: str, page_text: str) -> dict:
        hist = "\n".join(f"{i+1}. {s['action']} {s.get('detail','')}".strip() for i, s in enumerate(run["steps"][-8:]))
        prompt = (
            f"You are operating a web browser to accomplish a goal for the owner. Look at the attached screenshot "
            f"(the browser viewport is {VW}x{VH} pixels; coordinates are measured from the top-left).\n\n"
            f"GOAL: {run['goal']}\n\n"
            f"Steps so far:\n{hist or '(none yet)'}\n\n"
            f"Visible page text (may be clipped):\n{page_text[:4000]}\n\n"
            "Decide the single next action. Reply with ONLY one JSON object, no prose:\n"
            '{\"thought\": \"<one short sentence>\", \"action\": \"navigate|click|type|scroll|key|read|done\", '
            '\"url\": \"<for navigate>\", \"x\": <int for click>, \"y\": <int for click>, \"text\": \"<for type>\", '
            '\"key\": \"<e.g. Enter>\", \"dy\": <pixels for scroll>, \"answer\": \"<for done: what you found>\"}\n'
            "Rules: one action only; click coordinates must be inside the screenshot; never try to enter passwords, "
            "payment details, or solve CAPTCHAs — if the goal needs those, use action done and say so. Use done when "
            "the goal is met or cannot be met.")
        tid = self.sup.create(run["project"], run["provider"], prompt, mode="chat", timeout=STEP_TIMEOUT,
                              images=[shot_path])
        end = time.time() + STEP_TIMEOUT + 30
        while time.time() < end:
            t = self.sup.final(tid)
            if t["state"] in TERMINAL and not json.loads(t["checkpoint"] or "{}").get("retried_as"):
                break
            if run["stop"].is_set():
                self.sup.cancel(tid)
                return {"action": "done", "answer": "stopped by owner"}
            time.sleep(0.5)
        t = self.sup.final(tid)
        if t["state"] != "COMPLETED":
            return {"action": "error", "detail": f"provider turn {t['state'].lower()}"}
        text = (json.loads(t["checkpoint"] or "{}").get("result") or self.sup.output(t["id"])[0]).strip()
        m = re.search(r"\{[\s\S]*\}", text)
        try:
            return json.loads(m.group(0)) if m else {"action": "error", "detail": "no JSON action returned"}
        except ValueError:
            return {"action": "error", "detail": "unreadable action"}

    def _do(self, act: dict) -> str:
        a = act.get("action")
        if a == "navigate":
            r = self.browser.cmd("navigate", url=str(act.get("url") or ""))
            return redact(r.get("url") or r.get("error") or "")
        if a == "click":
            x = max(0, min(VW, int(act.get("x", VW // 2)))); y = max(0, min(VH, int(act.get("y", VH // 2))))
            self.browser.cmd("click", x=x, y=y)
            return f"({x},{y})"
        if a == "type":
            r = self.browser.cmd("type", text=str(act.get("text", ""))[:400], agent=True)
            return redact(str(act.get("text", ""))[:60]) + ("" if r.get("ok") else f" [{r.get('error')}]")
        if a == "key":
            self.browser.cmd("key", key=str(act.get("key", "Enter")))
            return str(act.get("key", "Enter"))
        if a == "scroll":
            self.browser.cmd("scroll", dy=int(act.get("dy", 600)))
            return str(act.get("dy", 600))
        if a == "read":
            return "(read the page)"
        return ""

    def _loop(self, run):
        import tempfile
        try:
            for _ in range(run["max_steps"]):
                if run["stop"].is_set():
                    run["answer"] = run.get("answer") or "Stopped by the owner."
                    break
                try:
                    png = self.browser.shot_png(False)
                    info = self.browser.cmd("text")
                except Exception as e:  # noqa: BLE001
                    run["steps"].append({"action": "error", "detail": f"browser: {type(e).__name__}"})
                    break
                fd = Path(tempfile.gettempdir()) / f"aesop-drive-{run['provider']}-{len(run['steps'])}.png"
                fd.write_bytes(png)
                try:
                    act = self._ask(run, str(fd), info.get("text") or "")
                finally:
                    try:
                        fd.unlink()
                    except OSError:
                        pass
                a = act.get("action")
                step = {"action": a, "thought": redact(str(act.get("thought", ""))[:200]),
                        "url": info.get("url"), "title": info.get("title")}
                if a == "done":
                    run["answer"] = redact(str(act.get("answer", "") or act.get("thought", "")))[:2000]
                    run["steps"].append(step)
                    break
                if a == "error":
                    step["detail"] = act.get("detail", "unclear action")
                    run["steps"].append(step)
                    if sum(1 for s in run["steps"][-3:] if s["action"] == "error") >= 3:
                        break
                    continue
                if a not in ("navigate", "click", "type", "key", "scroll", "read"):
                    step.update(action="error", detail=f"unknown action {a!r}")
                    run["steps"].append(step)
                    continue
                step["detail"] = self._do(act)
                run["steps"].append(step)
                self.store.event("browse_step", run["project"]["id"], provider=run["provider"], action=a)
            run["state"] = "DONE"
        except Exception as e:  # noqa: BLE001 - never crash the server thread
            run["state"] = "FAILED"
            run["steps"].append({"action": "error", "detail": f"{type(e).__name__}"})
        finally:
            if run["state"] == "RUNNING":
                run["state"] = "DONE"
