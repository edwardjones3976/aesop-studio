"""Roundtable session drafts, strict preflight, planning-packet export, and the labelled non-live fallback.

Live sessions run through roundtable_live.Broker once this strict preflight passes, including the owner's
"Live roundtables" switch (off by default). A checked lane is a
per-session owner selection only: it never changes routes, permits, transfer policies or credentials.
"""
from __future__ import annotations

import json
import time

from . import lanes as lane_mod
from .store import Store, new_id

MODES = {"general": {"default_min": 15, "allowed_min": (5, 10, 15, 20, 30), "min_speakers": 4},
         "war_room": {"default_min": 8, "allowed_min": (4, 6, 8, 10), "min_speakers": 3}}
OUTCOMES = ("architecture review", "adversarial challenge", "code design", "research synthesis",
            "creative ideation", "incident diagnosis")
RESPONSE_WINDOWS = (15, 30, 45)

SCHEMA = """
CREATE TABLE IF NOT EXISTS roundtables(
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), mode TEXT NOT NULL, objective TEXT NOT NULL,
  deliverable TEXT NOT NULL, outcome_type TEXT NOT NULL, time_limit_min INTEGER NOT NULL, response_window_s INTEGER,
  roster TEXT NOT NULL, sharing_ack INTEGER NOT NULL, caps TEXT NOT NULL, status TEXT NOT NULL,
  compare TEXT NOT NULL DEFAULT '[]', created REAL NOT NULL, updated REAL NOT NULL);
"""


def ensure_schema(store: Store) -> None:
    with store.conn() as c:
        c.executescript(SCHEMA)


def _clean(body: dict) -> dict:
    mode = body.get("mode") if body.get("mode") in MODES else "general"
    spec = MODES[mode]
    tmin = int(body.get("time_limit_min") or spec["default_min"])
    if tmin not in spec["allowed_min"]:
        raise ValueError(f"time limit for {mode} must be one of {spec['allowed_min']} minutes")
    win = body.get("response_window_s")
    win = int(win) if win not in (None, "") else (30 if mode == "war_room" else None)
    if mode == "war_room" and win not in RESPONSE_WINDOWS:
        raise ValueError("War Room response window must be 15, 30 or 45 seconds")
    outcome = body.get("outcome_type") or OUTCOMES[0]
    if outcome not in OUTCOMES:
        raise ValueError("unknown outcome type")
    caps = body.get("caps") or {}
    caps = {"max_turns": max(1, min(200, int(caps.get("max_turns") or 24))),
            "max_messages_per_speaker": max(1, min(50, int(caps.get("max_messages_per_speaker") or 6))),
            "cost_cap_usd": max(0.0, min(165.0, float(caps.get("cost_cap_usd") or 0))),
            # Researcher lane (public web search on request); on by default, the owner can switch it off per draft
            "research": caps.get("research") is not False,
            "max_research": max(0, min(20, int(caps["max_research"]) if caps.get("max_research") not in (None, "")
                                else 8))}
    roster = [str(x)[:64] for x in (body.get("roster") or [])][:32]
    return {"mode": mode, "objective": str(body.get("objective") or "").strip()[:4000],
            "deliverable": str(body.get("deliverable") or "").strip()[:500], "outcome_type": outcome,
            "time_limit_min": tmin, "response_window_s": win if mode == "war_room" else None,
            "roster": list(dict.fromkeys(roster)), "sharing_ack": bool(body.get("sharing_ack")), "caps": caps}


def save(store: Store, project_id: str, body: dict) -> dict:
    ensure_schema(store)
    d = _clean(body)
    now = time.time()
    rid = body.get("id")
    existing = get(store, rid) if rid else None
    if existing and existing["project_id"] != project_id:
        raise KeyError("roundtable not in this project")
    if existing and (existing.get("live_status") or "DRAFT") != "DRAFT":
        raise ValueError("this roundtable already ran; its record is immutable — save a new draft instead")
    prior = {r["lane"]: r["approved_at"] for r in (existing or {}).get("roster", [])}
    roster = [{"lane": l, "approved": True, "approved_at": prior.get(l, now)} for l in d["roster"]]
    if existing:
        store.x("UPDATE roundtables SET mode=?,objective=?,deliverable=?,outcome_type=?,time_limit_min=?,"
                "response_window_s=?,roster=?,sharing_ack=?,caps=?,updated=? WHERE id=?",
                (d["mode"], d["objective"], d["deliverable"], d["outcome_type"], d["time_limit_min"],
                 d["response_window_s"], json.dumps(roster), int(d["sharing_ack"]), json.dumps(d["caps"]), now, rid))
    else:
        rid = new_id("rt")
        store.x("INSERT INTO roundtables(id,project_id,mode,objective,deliverable,outcome_type,time_limit_min,"
                "response_window_s,roster,sharing_ack,caps,status,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rid, project_id, d["mode"], d["objective"], d["deliverable"], d["outcome_type"], d["time_limit_min"],
                 d["response_window_s"], json.dumps(roster), int(d["sharing_ack"]), json.dumps(d["caps"]),
                 "DRAFT", now, now))
    store.event("roundtable_draft", project_id, roundtable_id=rid, mode=d["mode"], roster=d["roster"])
    return get(store, rid, with_preflight=True)


def get(store: Store, rid: str, with_preflight: bool = False) -> dict | None:
    ensure_schema(store)
    r = store.one("SELECT * FROM roundtables WHERE id=?", (rid,))
    if not r:
        return None
    for k in ("roster", "caps", "compare"):
        r[k] = json.loads(r[k])
    for k in ("speaker_state", "coverage", "consent"):
        if isinstance(r.get(k), str) and r[k]:
            r[k] = json.loads(r[k])
    r["sharing_ack"] = bool(r["sharing_ack"])
    if with_preflight:
        r["preflight"] = preflight(store, r)
    return r


def list_for(store: Store, project_id: str) -> list[dict]:
    ensure_schema(store)
    return [get(store, r["id"]) for r in
            store.q("SELECT id FROM roundtables WHERE project_id=? ORDER BY updated DESC LIMIT 50", (project_id,))]


def preflight(store: Store, rec: dict, discovered: dict | None = None) -> dict:
    disc = discovered or lane_mod.discover(store)
    by_id = {l["id"]: l for l in disc["lanes"]}
    selected = [r["lane"] for r in rec["roster"]]
    unknown = [l for l in selected if l not in by_id]
    lanes = [by_id[l] for l in selected if l in by_id]
    qualified = [l for l in lanes if l["counts_as_speaker"]]
    mode = rec["mode"]
    checks = []

    def check(cid, label, ok, detail=""):
        checks.append({"id": cid, "label": label, "pass": bool(ok), "detail": detail})

    check("objective", "Written purpose (objective)", len(rec["objective"]) >= 10,
          "at least 10 characters" if len(rec["objective"]) < 10 else "")
    check("deliverable", "Desired deliverable", bool(rec["deliverable"]))
    check("roster_known", "Every selected lane exists in live discovery", not unknown,
          f"unknown lanes: {', '.join(unknown)}" if unknown else "")
    if mode == "general":
        check("speakers", "At least 4 qualified speakers (General)", len(qualified) >= 4,
              f"{len(qualified)} qualified of {len(selected)} selected; research/review lanes never count")
    else:
        admins = {l["id"] for l in lanes if l["lane_class"] == "admin"}
        non_admin = [l["id"] for l in lanes if l["lane_class"] != "admin"]
        check("admins_only", "War Room membership is administrators only", not non_admin,
              f"non-admin lanes selected: {', '.join(non_admin)}" if non_admin else "")
        check("admin_seats", "All three documented administrators selected", admins == set(lane_mod.ADMINS),
              f"selected admins: {', '.join(sorted(admins)) or 'none'}")
        check("admin_ready", "Each administrator has a verified in-app route",
              all(l["counts_as_speaker"] for l in lanes if l["lane_class"] == "admin") and len(admins) == 3,
              ", ".join(f"{l['id']}: {l['readiness']}" for l in lanes if l["lane_class"] == "admin"))
    not_ready = [l["id"] for l in lanes if l["lane_class"] in ("admin", "speaker") and not l["counts_as_speaker"]]
    check("funding", "Every selected speaker has a known funding source or included route", not not_ready,
          f"no verified route/funding: {', '.join(not_ready)}" if not_ready else "")
    check("sharing", "External-sharing preview acknowledged", rec["sharing_ack"])
    caps = rec["caps"]
    check("caps", "Turn/message ceilings and cost cap set",
          caps["max_turns"] > 0 and caps["max_messages_per_speaker"] > 0,
          f"{caps['max_turns']} turns · {caps['max_messages_per_speaker']}/speaker · cost cap ${caps['cost_cap_usd']:.2f}")
    live = rec.get("live_status") or "DRAFT"
    check("fresh", "Session has not run yet", live == "DRAFT",
          "" if live == "DRAFT" else f"this session is {live}; save a new draft (nothing is replayed)")
    metered = [l["id"] for l in lanes if l["counts_as_speaker"] and l["route_type"] == "separately billed API"]
    check("cost_cap", "Cost cap covers metered speakers", not metered or caps["cost_cap_usd"] > 0,
          f"{', '.join(metered)} bill per token: set a cost cap above $0" if metered and caps["cost_cap_usd"] <= 0
          else ("all speakers on included plan quota ($0 incremental)" if not metered else ""))
    for g in disc["mission_gates"]:
        check(g["code"].lower(), g["code"].replace("_", " ").title(), False, g["reason"])
    blocks = [f"{c['label']}: {c['detail'] or 'not met'}" for c in checks if not c["pass"]]
    return {"checks": checks, "selected": len(selected), "qualified_speakers": len(qualified),
            "start_allowed": not blocks, "block_reasons": blocks}


def export_packet(store: Store, rec: dict, project: dict) -> dict:
    disc = lane_mod.discover(store)
    sel = {r["lane"] for r in rec["roster"]}
    live = rec.get("live_status") or "DRAFT"
    cmp = rec.get("compare") if isinstance(rec.get("compare"), dict) else None
    if live == "DRAFT" and not cmp:
        status, note = "PLANNING_ONLY_NOT_EXECUTED", (
            "Planning packet only. No provider was contacted to produce it; checked lanes are per-session "
            "selections and grant no authority, credentials, routing or spend.")
    elif live == "DRAFT" and cmp:
        status, note = "PLANNING_WITH_COMPARE", (
            "Draft export including any stored side-by-side compare results. Compare used read-only chat turns only.")
    else:
        status, note = "LIVE_SESSION_RECORD", (
            f"Session record export (live_status={live}). Transcript and memo reflect brokered read-only chat; "
            "nothing was executed from provider replies.")
    session_keys = ("id", "mode", "objective", "deliverable", "outcome_type", "time_limit_min", "response_window_s",
                    "roster", "sharing_ack", "caps", "status", "created", "updated", "live_status", "started", "ended",
                    "memo", "coverage", "compare")
    return {"format": "aesop-roundtable-planning-packet/2", "status": status, "note": note,
            "project": {"id": project["id"], "name": project["name"]},
            "session": {k: rec[k] for k in session_keys if k in rec},
            "preflight": preflight(store, rec, disc),
            "lanes_at_export": [{k: l[k] for k in ("id", "name", "lane_class", "readiness", "route_type",
                                                   "conversation_support", "counts_as_speaker", "reasons")}
                                | {"selected": l["id"] in sel} for l in disc["lanes"]],
            "exported_at": time.time()}
