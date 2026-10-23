"""Run a live Admin War Room (Codex, Claude Code, Cursor) on the owner's Studio data, with the owner's approval.

The objective carries a factual visual brief, because the participants answer through text-only, read-only
chat routes and cannot see screenshots.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from aesop_studio import lanes, roundtable  # noqa: E402
from aesop_studio.roundtable_live import Broker  # noqa: E402
from aesop_studio.services import Services  # noqa: E402
from aesop_studio.store import Store  # noqa: E402
from aesop_studio.tasks import Supervisor  # noqa: E402

BRIEF = """Critique the VISUAL DESIGN of Aesop Studio and agree the 5 highest-impact visual improvements.
Facts about the current UI (from the design contract, 49 QA screenshots at 7 viewports, and a paid visual review):
- Theme "Coal / Ember", dark only: canvas #0B111A, panels #141F2C, raised #243243, hairline borders #2B3B4D,
  text #EEF4FA / #AFBED0, one coral primary action #FF916C (dark text), mint #80E1CB for verified, sky focus #9BD7FF.
  Segoe UI Variable; 14px body, 22px workspace heading; 12px panel radius; subtle shadows.
- Layout: 60px topbar (logo, breadcrumb Project / Workspace / Activity, Ctrl+K search, provider+route chip, help,
  inspector toggle), 64-68px icon+label rail (Chat, Build, Research, Memory, Saved; Providers/Evidence at bottom),
  220-248px project explorer with initials avatars and a coral 'New project' button, flexible canvas, 320-400px
  inspector with tabs Preview/Files/Changes/Terminal/Logs. Mobile: bottom nav, one column.
- Chat: message cards with avatar initials, provider name + access-route chip + status pill, cost line for metered
  calls; composer card with attachment chips, Ctrl+Enter hint, 'Preview context' and a coral Send.
- Research: two-column forms (Add a source / Record a finding), proposals in dashed sky cards.
- Evidence: KPI tiles for budget, tables for acceptance/latency/research.
- QA status: 0 horizontal overflow at 360-1920px, all controls >=40px, WCAG text contrast 5.9-17:1.
- Known weaknesses: the project header block (title, root path chip, provider chips, Settings) repeats the topbar and
  takes ~170px before content; two coral buttons can be visible at once (New project + Send/Start); dark-only;
  dense metadata chips; tables are plain; empty states are text-heavy; no light theme or brand illustration."""


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    store = Store(Path(os.environ["LOCALAPPDATA"]) / "AesopStudio")
    sup = Supervisor(store)
    svc = Services(store, sup)
    lanes.set_live_authorized(store, True)  # owner-approved in chat for this run
    root = ROOT / ".sandbox" / "warroom"
    root.mkdir(parents=True, exist_ok=True)
    proj = next((p for p in svc.projects() if p["name"] == "Aesop Studio design review"), None) \
        or svc.create_project("Aesop Studio design review", str(root), "claude")
    rec = roundtable.save(store, proj["id"], {
        "mode": "war_room", "objective": BRIEF, "deliverable": "ranked list of 5 visual changes with CSS-level specifics",
        "outcome_type": "adversarial challenge", "time_limit_min": 8, "response_window_s": 45, "roster": list(lanes.ADMINS),
        "sharing_ack": True, "caps": {"max_turns": 12, "max_messages_per_speaker": 3, "cost_cap_usd": 0}})
    pf = rec["preflight"]
    print("preflight:", pf["start_allowed"], pf["block_reasons"])
    if not pf["start_allowed"]:
        return
    broker = Broker(store, sup)
    print("reconciled earlier sessions:", broker.reconcile())
    res = broker.start(rec, svc.project(proj["id"]))
    print("started:", res["started"])
    seen = 0
    while True:
        st = broker.status(rec["id"])
        for e in broker.events(rec["id"], seen):
            seen = e["seq"]
            who = st["speakers"].get(e["speaker"], {}).get("name", e["speaker"] or "relay")
            meta = f" ({e['latency_s']}s, saw up to {e['seen_label']})" if e["kind"] in ("opening", "message") else ""
            print(f"\n[{e['label']}] {e['kind'].upper()} {who}{meta}:\n{e['content'][:1800]}", flush=True)
        if st["live_status"] not in ("RUNNING", "PAUSED"):
            break
        time.sleep(1)
    print("\nFINAL:", st["live_status"], "| elapsed", st["elapsed_s"], "s |", st["coverage"].get("summary"))
    out = ROOT / "docs" / "roundtables" / f"warroom-visual-{time.strftime('%Y%m%d-%H%M')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(broker.export(rec["id"]), indent=1, default=str), encoding="utf-8")
    print("record:", out)


if __name__ == "__main__":
    main()
