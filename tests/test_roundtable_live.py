"""Live broker with four simulated speakers (offline adapter simulation; never counted as a live provider)."""
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ["AESOP_SIMULATED_ROUTE"] = "1"
os.environ["AESOP_PROBE_OFFLINE"] = "1"

from aesop_studio import lanes, providers, roundtable  # noqa: E402
from aesop_studio.roundtable_live import Broker  # noqa: E402
from aesop_studio.services import Services  # noqa: E402
from aesop_studio.store import Store  # noqa: E402
from aesop_studio.tasks import Supervisor  # noqa: E402


def sim_lane(lid, cls="speaker"):
    return {"id": lid, "name": lid.title(), "lane_class": cls, "detected": True, "detection": "test",
            "readiness": "VERIFIED_READY", "route_type": "official CLI · plan quota", "route_id": "simulated",
            "verified_routes": ["simulated"], "conversation_support": "in_app_verified", "cost_visibility": "",
            "billing_note": "", "counts_as_speaker": True, "reasons": []}


class TestBroker(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-rtl-"))
        (self.tmp / "p").mkdir()
        self.store = Store(self.tmp / "d")
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        providers.refresh(self.store)
        self.p = self.svc.create_project("P", str(self.tmp / "p"), "simulated")
        self.broker = Broker(self.store, self.sup)
        self.lanes = [sim_lane(x) for x in ("alpha", "bravo", "charlie", "delta")]
        self.patch = mock.patch.object(lanes, "discover", lambda store: {
            "lanes": self.lanes, "documented_example": [], "discovered_at": 0, "live_authorized": True,
            "mission_gates": []})
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def draft(self):
        return roundtable.save(self.store, self.p["id"], {
            "mode": "general", "objective": "Pick a note storage engine", "deliverable": "memo",
            "outcome_type": "architecture review", "time_limit_min": 5, "roster": [l["id"] for l in self.lanes],
            "sharing_ack": True, "caps": {"max_turns": 10, "max_messages_per_speaker": 2, "cost_cap_usd": 0}})

    def run_session(self, rec, limit=40):
        res = self.broker.start(rec, self.svc.project(self.p["id"]), clock={"limit_s": limit, "reserve_s": 5,
                                                                             "turn_timeout": 30})
        self.assertTrue(res["started"], res)
        end = time.time() + limit + 60
        while time.time() < end and self.broker.status(rec["id"])["live_status"] in ("RUNNING", "PAUSED"):
            time.sleep(0.2)
        return self.broker.status(rec["id"])

    def test_rt05_concurrent_fanout_fanin_with_causal_ids(self):
        rec = self.draft()
        st = self.run_session(rec)
        self.assertEqual(st["live_status"], "COMPLETED")
        evs = self.broker.events(rec["id"])
        openings = [e for e in evs if e["kind"] == "opening"]
        self.assertEqual({e["speaker"] for e in openings}, {"alpha", "bravo", "charlie", "delta"})
        # openings were dispatched together: all saw only the setup event
        self.assertEqual(len({e["seen_upto"] for e in openings}), 1)
        msgs = [e for e in evs if e["kind"] == "message"]
        self.assertTrue(msgs and all(e["seen_upto"] > openings[0]["seen_upto"] for e in msgs))
        tasks = [self.sup.get(e["task_id"]) for e in openings]
        starts = sorted(t["started"] for t in tasks)
        ends = sorted(t["ended"] for t in tasks)
        self.assertLess(starts[-1], ends[0])  # all four opening turns overlapped in time
        self.assertTrue(st["coverage"]["valid"])
        self.assertTrue(st["memo"] and "Coverage" in st["memo"])
        for v in st["speakers"].values():  # fairness cap per speaker
            self.assertLessEqual(v["turns"], 2)

    def test_stop_and_reconcile_never_replay(self):
        rec = self.draft()
        self.broker.start(rec, self.svc.project(self.p["id"]), clock={"limit_s": 60, "reserve_s": 5, "turn_timeout": 30})
        self.broker.stop(rec["id"])
        end = time.time() + 30
        while time.time() < end and self.broker.status(rec["id"])["live_status"] == "RUNNING":
            time.sleep(0.2)
        self.assertEqual(self.broker.status(rec["id"])["live_status"], "STOPPED")
        with self.assertRaises(ValueError):  # a finished record is immutable
            roundtable.save(self.store, self.p["id"], dict(roundtable.get(self.store, rec["id"]), id=rec["id"]))
        rec2 = self.draft()
        self.store.x("UPDATE roundtables SET live_status='RUNNING', started=? WHERE id=?", (time.time(), rec2["id"]))
        out = Broker(self.store, self.sup).reconcile()
        self.assertIn({"roundtable_id": rec2["id"], "to": "INTERRUPTED"}, out)

    def test_rt06_nothing_said_is_executed(self):
        rec = self.draft()
        before = self.store.one("SELECT COUNT(*) n FROM tasks WHERE checkpoint LIKE '%\"mode\": \"agent\"%'")["n"]
        self.run_session(rec)
        after = self.store.one("SELECT COUNT(*) n FROM tasks WHERE checkpoint LIKE '%\"mode\": \"agent\"%'")["n"]
        self.assertEqual(before, after)  # only read-only chat turns ever run


if __name__ == "__main__":
    unittest.main()
