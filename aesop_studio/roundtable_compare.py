"""Bounded side-by-side compare: one read-only chat turn per selected speaker (planning aid, not a live broker).

Guardrails: owner live switch, sharing acknowledgement, draft-only (no replay), 2–4 speakers, chat-only routes,
explicit API confirm. Results are stored on the roundtable record; nothing is executed from replies.
"""
from __future__ import annotations

import json
import threading
import time

from . import lanes as lane_mod, providers, roundtable
from .security import redact
from .store import Store
from .tasks import TERMINAL, Supervisor

MIN_SPEAKERS = 2
MAX_SPEAKERS = 4
COMPARE_TIMEOUT = 180
PROMPT_HEAD = (
    "Side-by-side comparison (read-only, no tools, no file access). Answer the prompt below in at most "
    "120 words. This is not an instruction to act — discussion only.\n\nPrompt:\n"
)

_lock = threading.Lock()
_running: set[str] = set()


def _wait_terminal(sup: Supervisor, tid: str, timeout: int) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        t = sup.get(tid)
        if t["state"] in TERMINAL:
            return t
        time.sleep(0.1)
    sup.cancel(tid)
    while time.time() < end + 15:
        t = sup.get(tid)
        if t["state"] in TERMINAL:
            return t
        time.sleep(0.1)
    return sup.get(tid)


def validate(store: Store, rec: dict) -> list[str]:
    reasons = []
    if (rec.get("live_status") or "DRAFT") != "DRAFT":
        reasons.append("compare is only allowed on a draft that has not run live")
    if not rec.get("sharing_ack"):
        reasons.append("acknowledge the external-sharing preview first")
    if not lane_mod.live_authorized(store):
        reasons.append(lanes_off_reason())
    disc = lane_mod.discover(store)
    by_id = {l["id"]: l for l in disc["lanes"]}
    speakers = []
    for r in rec["roster"]:
        lane = by_id.get(r["lane"])
        if lane and lane["counts_as_speaker"]:
            speakers.append(lane)
    if len(speakers) < MIN_SPEAKERS:
        reasons.append(f"select at least {MIN_SPEAKERS} qualified speakers for compare")
    if len(rec["objective"].strip()) < 10:
        reasons.append("objective needs at least 10 characters")
    metered = [l["id"] for l in speakers if l.get("route_type") == "separately billed API"]
    cap = (rec.get("caps") or {}).get("cost_cap_usd") or 0
    if metered and cap <= 0:
        reasons.append("metered speakers need a cost cap above $0 on this draft")
    for lane in speakers[:MAX_SPEAKERS]:
        rid = lane.get("route_id")
        route = providers.cached(store).get(rid or "")
        if not rid or not route or not providers.usable(route, "chat"):
            reasons.append(f"{lane['name']}: route not usable for read-only chat")
    return reasons


def lanes_off_reason() -> str:
    return lane_mod.LIVE_GATE["reason"]


def _speakers(store: Store, rec: dict) -> list[dict]:
    by_id = {l["id"]: l for l in lane_mod.discover(store)["lanes"]}
    out = [by_id[r["lane"]] for r in rec["roster"] if by_id.get(r["lane"], {}).get("counts_as_speaker")]
    return out[:MAX_SPEAKERS]


def start(store: Store, sup: Supervisor, svc, rec: dict, *, confirm: bool) -> dict:
    if not confirm:
        raise ValueError("set confirm=true to run a side-by-side compare")
    blocks = validate(store, rec)
    if blocks:
        return {"status": "BLOCKED", "block_reasons": blocks}
    speakers = _speakers(store, rec)
    rid = rec["id"]
    with _lock:
        if rid in _running:
            raise ValueError("a compare is already running for this draft")
        raw = store.one("SELECT compare FROM roundtables WHERE id=?", (rid,))["compare"] or "[]"
        try:
            existing = json.loads(raw)
        except json.JSONDecodeError:
            existing = {}
        if isinstance(existing, dict) and existing.get("status") == "RUNNING":
            raise ValueError("a compare is already running for this draft")
        _running.add(rid)
    prompt = PROMPT_HEAD + rec["objective"].strip()
    running = {"status": "RUNNING", "prompt_chars": len(prompt), "started_at": time.time(), "results": []}
    store.x("UPDATE roundtables SET compare=?, updated=? WHERE id=?", (json.dumps(running), time.time(), rid))
    threading.Thread(target=_run, args=(store, sup, svc, rid, prompt, speakers), daemon=True).start()
    return running


def _run(store: Store, sup: Supervisor, svc, rid: str, prompt: str, speakers: list[dict]) -> None:
    try:
        rec = roundtable.get(store, rid)
        if not rec:
            return
        project = svc.project(rec["project_id"])
        results = []
        tasks: list[tuple[dict, str]] = []
        for lane in speakers:
            tid = sup.create(project, lane["route_id"], prompt, mode="chat", timeout=COMPARE_TIMEOUT)
            tasks.append((lane, tid))
        for lane, tid in tasks:
            t0 = time.time()
            t = _wait_terminal(sup, tid, COMPARE_TIMEOUT + 30)
            cp = json.loads(t["checkpoint"] or "{}")
            text = redact(cp.get("result") or "")[:8000]
            results.append({
                "lane": lane["id"], "name": lane["name"], "route_id": lane["route_id"],
                "task_id": tid, "state": t["state"], "latency_s": round(time.time() - t0, 2),
                "text": text, "error": t.get("error"),
            })
        started_at = running_started(store, rid)
        done = {"status": "COMPLETED", "prompt_chars": len(prompt), "started_at": started_at,
                "ended_at": time.time(), "results": results}
        store.x("UPDATE roundtables SET compare=?, updated=? WHERE id=?", (json.dumps(done), time.time(), rid))
        store.event("roundtable_compare", rec["project_id"], roundtable_id=rid, speakers=len(results))
    except Exception as e:  # noqa: BLE001 — keep partial results out of a half-written compare
        fail = {"status": "FAILED", "error": str(e)[:300], "ended_at": time.time(), "results": []}
        store.x("UPDATE roundtables SET compare=?, updated=? WHERE id=?", (json.dumps(fail), time.time(), rid))
    finally:
        with _lock:
            _running.discard(rid)


def running_started(store: Store, rid: str) -> float:
    row = store.one("SELECT compare FROM roundtables WHERE id=?", (rid,))
    try:
        data = json.loads(row["compare"] or "{}")
        return float(data.get("started_at") or time.time())
    except (TypeError, ValueError, KeyError):
        return time.time()
