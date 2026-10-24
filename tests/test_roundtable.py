"""Roundtable planning (design-ready, non-executing), lane discovery and the provider naming rule."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ["AESOP_SIMULATED_ROUTE"] = "1"
os.environ["AESOP_PROBE_OFFLINE"] = "1"

from aesop_studio import lanes, ledger, providers, roundtable, roundtable_compare  # noqa: E402
from aesop_studio.services import Services  # noqa: E402
from aesop_studio.store import Store  # noqa: E402
from aesop_studio.tasks import Supervisor  # noqa: E402


def fake_lane(lid, cls="speaker", speaker=True, readiness="VERIFIED_READY", route_id=None):
    rid = route_id if route_id is not None else lid
    return {"id": lid, "name": lid.title(), "lane_class": cls, "detected": True, "detection": "test",
            "readiness": readiness, "route_type": "official CLI · plan quota", "route_id": rid,
            "verified_routes": [rid], "conversation_support": "in_app_verified" if speaker else "none",
            "cost_visibility": "plan quota", "billing_note": "", "counts_as_speaker": speaker, "reasons": []}


def disc(*lanes_, gates=True):
    return {"lanes": list(lanes_), "documented_example": [], "discovered_at": 0,
            "mission_gates": lanes.MISSION_GATES if gates else []}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-rt-"))
        (self.tmp / "p").mkdir()
        self.store = Store(self.tmp / "d")
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        providers.refresh(self.store)
        self.p = self.svc.create_project("P", str(self.tmp / "p"), "simulated")

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def draft(self, **kw):
        body = {"mode": "general", "objective": "Choose a storage engine for project notes", "deliverable": "memo",
                "outcome_type": "architecture review", "time_limit_min": 15, "roster": [], "sharing_ack": True,
                "caps": {"max_turns": 20, "max_messages_per_speaker": 5, "cost_cap_usd": 0}}
        body.update(kw)
        return roundtable.save(self.store, self.p["id"], body)


class TestDiscovery(Base):
    def test_rt01_lists_documented_lanes_and_registry_extras(self):
        d = lanes.discover(self.store)
        names = {l["name"] for l in d["lanes"]}
        for n in lanes.DOCUMENTED_EXAMPLE:
            self.assertIn(n, names)  # undetected ones still appear, as NOT_DETECTED
        self.assertTrue(any(l["id"] == "route:simulated" and not l["counts_as_speaker"] for l in d["lanes"]))
        research = [l for l in d["lanes"] if l["lane_class"] == "research"]
        self.assertTrue(research and not any(l["counts_as_speaker"] for l in research))
        self.assertTrue(d["mission_gates"])

    def test_naming_rule_code_based_titles(self):
        routes = providers.cached(self.store)
        self.assertEqual(routes["codex"]["display_name"], "Codex")
        self.assertEqual(routes["openai-api"]["display_name"], "Codex API")
        self.assertEqual(routes["claude"]["display_name"], "Claude Code")
        for r in routes.values():
            self.assertNotIn("OpenAI", r["display_name"])
            self.assertNotIn("ChatGPT", r["display_name"])
        lane_names = [l["name"] for l in lanes.discover(self.store)["lanes"]]
        self.assertFalse([n for n in lane_names if "OpenAI" in n or "ChatGPT" in n])
        self.assertIn("Codex", lane_names)


class TestPlanning(Base):
    def test_rt02_approval_is_per_session_and_grants_nothing(self):
        before = (json.dumps(providers.cached(self.store), sort_keys=True), ledger.permit_enabled(self.store),
                  json.dumps(self.svc.project(self.p["id"])["transfer_policy"]))
        rec = self.draft(roster=["openai", "claude", "perplexity"])
        self.assertEqual([r["lane"] for r in rec["roster"]], ["openai", "claude", "perplexity"])
        self.assertTrue(all(r["approved"] and r["approved_at"] for r in rec["roster"]))
        after = (json.dumps(providers.cached(self.store), sort_keys=True), ledger.permit_enabled(self.store),
                 json.dumps(self.svc.project(self.p["id"])["transfer_policy"]))
        self.assertEqual(before, after)
        again = roundtable.save(self.store, self.p["id"], dict(rec, roster=["openai", "claude"]))
        self.assertEqual(again["roster"][0]["approved_at"], rec["roster"][0]["approved_at"])  # consent time kept

    def test_rt03_general_needs_four_qualified_research_never_counts(self):
        rec = self.draft(roster=["a", "b", "c", "r1"])
        d = disc(fake_lane("a"), fake_lane("b"), fake_lane("c"), fake_lane("r1", "research", speaker=False))
        pf = roundtable.preflight(self.store, rec, d)
        self.assertEqual(pf["qualified_speakers"], 3)
        self.assertFalse(next(c for c in pf["checks"] if c["id"] == "speakers")["pass"])
        rec4 = self.draft(roster=["a", "b", "c", "e"])
        pf4 = roundtable.preflight(self.store, rec4, disc(fake_lane("a"), fake_lane("b"), fake_lane("c"),
                                                          fake_lane("e")))
        self.assertTrue(next(c for c in pf4["checks"] if c["id"] == "speakers")["pass"])

    def test_rt04_war_room_admins_only_with_three_seat_exception(self):
        admins = [fake_lane(a, "admin") for a in lanes.ADMINS]
        rec = self.draft(mode="war_room", time_limit_min=8, response_window_s=30, roster=list(lanes.ADMINS))
        pf = roundtable.preflight(self.store, rec, disc(*admins))
        checks = {c["id"]: c["pass"] for c in pf["checks"]}
        self.assertTrue(checks["admins_only"] and checks["admin_seats"] and checks["admin_ready"])
        self.assertNotIn("speakers", checks)  # no four-provider minimum for the War Room
        rec2 = self.draft(mode="war_room", time_limit_min=8, response_window_s=30,
                          roster=list(lanes.ADMINS) + ["grok"])
        pf2 = roundtable.preflight(self.store, rec2, disc(*admins, fake_lane("grok")))
        self.assertFalse({c["id"]: c["pass"] for c in pf2["checks"]}["admins_only"])

    def test_rt10_start_needs_owner_switch(self):
        rec = self.draft(roster=["a", "b", "c", "e"])
        pf = roundtable.preflight(self.store, rec, disc(*(fake_lane(x) for x in "abce")))
        self.assertFalse(pf["start_allowed"])
        self.assertTrue(any("Live sessions are off" in b for b in pf["block_reasons"]))  # owner switch is off by default
        lanes.set_live_authorized(self.store, True)
        pf2 = roundtable.preflight(self.store, rec, disc(*(fake_lane(x) for x in "abce"), gates=False))
        self.assertTrue(pf2["start_allowed"], pf2["block_reasons"])

    def test_validation_and_export_packet(self):
        with self.assertRaises(ValueError):
            self.draft(time_limit_min=17)
        with self.assertRaises(ValueError):
            self.draft(mode="war_room", time_limit_min=8, response_window_s=20)
        rec = self.draft(roster=["openai"])
        pkt = roundtable.export_packet(self.store, rec, self.svc.project(self.p["id"]))
        self.assertEqual(pkt["status"], "PLANNING_ONLY_NOT_EXECUTED")
        self.assertTrue(any(l["selected"] for l in pkt["lanes_at_export"]))

    def test_verify_rejects_non_cli_routes(self):
        with self.assertRaises(ValueError):
            providers.verify_live(self.store, "openai-api")

    def test_compare_needs_live_switch_and_confirm(self):
        rec = self.draft(roster=["a", "b"])
        lane_disc = disc(fake_lane("a", route_id="simulated"), fake_lane("b", route_id="simulated"), gates=False)
        with mock.patch.object(lanes, "discover", lambda store: lane_disc):
            blocked = roundtable_compare.start(self.store, self.sup, self.svc, rec, confirm=True)
        self.assertEqual(blocked["status"], "BLOCKED")
        lanes.set_live_authorized(self.store, True)
        with mock.patch.object(lanes, "discover", lambda store: lane_disc):
            with self.assertRaises(ValueError):
                roundtable_compare.start(self.store, self.sup, self.svc, rec, confirm=False)

    def test_compare_runs_parallel_simulated(self):
        import time as _time
        lanes.set_live_authorized(self.store, True)
        rec = self.draft(roster=["a", "b"])
        lane_disc = disc(fake_lane("a", route_id="simulated"), fake_lane("b", route_id="simulated"), gates=False)
        with mock.patch.object(lanes, "discover", lambda store: lane_disc):
            out = roundtable_compare.start(self.store, self.sup, self.svc, rec, confirm=True)
        self.assertEqual(out["status"], "RUNNING")
        end = _time.time() + 45
        while _time.time() < end:
            row = roundtable.get(self.store, rec["id"])
            cmp = row["compare"]
            if isinstance(cmp, dict) and cmp.get("status") in ("COMPLETED", "FAILED"):
                break
            _time.sleep(0.15)
        row = roundtable.get(self.store, rec["id"])
        cmp = row["compare"]
        self.assertEqual(cmp["status"], "COMPLETED")
        self.assertEqual(len(cmp["results"]), 2)
        self.assertTrue(all(r["state"] == "COMPLETED" and "[simulated chat]" in r["text"] for r in cmp["results"]))


if __name__ == "__main__":
    unittest.main()
