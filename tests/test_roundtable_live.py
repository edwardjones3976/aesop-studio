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


def _ci_flaky_retry(test_method):
    """Retry timing-sensitive broker tests under GitHub Actions (see docs/PROJECT-BRIEFING-20261026.md)."""

    def wrapper(self):
        attempts = 3 if os.environ.get("GITHUB_ACTIONS") == "true" else 1
        last = None
        for attempt in range(attempts):
            try:
                return test_method(self)
            except AssertionError as exc:
                last = exc
                if attempt + 1 >= attempts:
                    raise
                self.tearDown()
                self.setUp()
        raise last  # pragma: no cover

    return wrapper


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

    @_ci_flaky_retry
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
        for lid in ("alpha", "bravo", "charlie", "delta"):  # fairness cap on open-floor messages per speaker
            self.assertLessEqual(len([e for e in msgs if e["speaker"] == lid]), 2)
        self.assertEqual({e["speaker"] for e in evs if e["kind"] == "closing"}, {"alpha", "bravo", "charlie", "delta"})
        # no lockstep barrier: the first floor message was dispatched before the slowest opening landed
        first_floor = min(self.sup.get(e["task_id"])["started"] for e in msgs)
        self.assertLess(first_floor, max(t["ended"] for t in tasks) + 1.0)

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

    @_ci_flaky_retry
    def test_switch_turns_off_after_conclusion_and_history_kept(self):
        import aesop_studio.roundtable_live as rl
        lanes.set_live_authorized(self.store, True)
        with mock.patch.object(rl, "AUTO_OFF_S", 0.5):
            rec = self.draft()
            st = self.run_session(rec)
            self.assertEqual(st["live_status"], "COMPLETED")
            end = time.time() + 10
            while time.time() < end and lanes.live_authorized(self.store):
                time.sleep(0.2)
        self.assertFalse(lanes.live_authorized(self.store))
        self.assertTrue(self.broker.events(rec["id"]))  # the conversation stays saved in history
        self.assertEqual(roundtable.get(self.store, rec["id"])["live_status"], "COMPLETED")

    def test_restart_switches_live_off(self):
        lanes.set_live_authorized(self.store, True)
        Broker(self.store, self.sup).reconcile()
        self.assertFalse(lanes.live_authorized(self.store))

    def test_rt06_nothing_said_is_executed(self):
        rec = self.draft()
        before = self.store.one("SELECT COUNT(*) n FROM tasks WHERE checkpoint LIKE '%\"mode\": \"agent\"%'")["n"]
        self.run_session(rec)
        after = self.store.one("SELECT COUNT(*) n FROM tasks WHERE checkpoint LIKE '%\"mode\": \"agent\"%'")["n"]
        self.assertEqual(before, after)  # only read-only chat turns ever run


if __name__ == "__main__":
    unittest.main()


class TestResearcher(TestBroker):
    def setUp(self):
        super().setUp()
        os.environ["AESOP_SIM_RESEARCH"] = "1"
        os.environ["AESOP_SIM_ASK_RESEARCH"] = "1"

    def tearDown(self):
        os.environ.pop("AESOP_SIM_RESEARCH", None)
        os.environ.pop("AESOP_SIM_ASK_RESEARCH", None)
        super().tearDown()

    def test_speakers_call_researcher_and_results_join_timeline(self):
        rec = roundtable.save(self.store, self.p["id"], {
            "mode": "general", "objective": "Pick a note storage engine", "deliverable": "memo",
            "outcome_type": "architecture review", "time_limit_min": 5, "roster": [l["id"] for l in self.lanes],
            "sharing_ack": True, "caps": {"max_turns": 10, "max_messages_per_speaker": 2, "cost_cap_usd": 0,
                                          "max_research": 2}})
        st = self.run_session(rec)
        self.assertEqual(st["live_status"], "COMPLETED")
        evs = self.broker.events(rec["id"])
        found = [e for e in evs if e["kind"] == "research"]
        self.assertEqual(len(found), 2)  # four openings asked, the session cap of 2 held
        self.assertTrue(all(e["speaker"] == "researcher" and e["reply_to"] for e in found))
        self.assertIn("Simulated source 1", found[0]["content"])
        self.assertTrue(any(e["kind"] == "gap" and "research cap" in e["content"] for e in evs))
        self.assertEqual(st["speakers"]["researcher"]["lookups"], 2)
        self.assertNotIn("Researcher", st["coverage"]["spoke"])  # never counted as a speaker
        self.assertIn("researcher", st["consent"])
        prompts = [self.sup.get(e["task_id"])["prompt"] for e in evs if e["kind"] == "message" and e["task_id"]]
        self.assertTrue(any("Researcher (web sources" in p for p in prompts))  # speakers saw the sources

    def test_owner_can_ask_and_switch_off(self):
        rec = self.draft()
        res = self.broker.start(rec, self.svc.project(self.p["id"]), clock={"limit_s": 30, "reserve_s": 5,
                                                                             "turn_timeout": 30})
        self.assertTrue(res["started"])
        q = self.broker.ask_research(rec["id"], "latest sqlite release notes")
        self.assertTrue(q["queued"])
        with self.assertRaises(ValueError):
            self.broker.ask_research(rec["id"], "x")
        end = time.time() + 90
        while time.time() < end and self.broker.status(rec["id"])["live_status"] in ("RUNNING", "PAUSED"):
            time.sleep(0.2)
        evs = self.broker.events(rec["id"])
        self.assertTrue(any(e["kind"] == "research" and "Owner" in e["content"] for e in evs))
        off = roundtable.save(self.store, self.p["id"], {**{k: rec[k] for k in ("mode", "objective", "deliverable",
                              "outcome_type", "time_limit_min")}, "roster": [l["id"] for l in self.lanes],
                              "sharing_ack": True, "caps": {"max_turns": 4, "max_messages_per_speaker": 1,
                                                            "research": False}})
        self.assertFalse(off["caps"]["research"])
        st = self.run_session(off, limit=20)
        self.assertNotIn("researcher", st["speakers"])


class TestFollowUp(TestBroker):
    @unittest.skip("exercised in TestBroker (avoid duplicate flaky timing run)")
    def test_rt05_concurrent_fanout_fanin_with_causal_ids(self):
        super().test_rt05_concurrent_fanout_fanin_with_causal_ids()

    def test_collect_parse_and_merge(self):
        from aesop_studio import followup
        evs = [{"kind": "opening", "speaker": "alpha", "label": "E2", "content":
                "Questions first:\n1. **Budget.** Does the $88 cover hosting?\n@Bravo do you agree?\nPOSITION: ask?"},
               {"kind": "message", "speaker": "bravo", "label": "E3", "content": "- Does the $88 budget cover hosting too?"},
               {"kind": "system", "speaker": None, "label": "E4", "content": "Which is ignored?"}]
        memo = "## Follow-ups\n- Which Bid Whist variant is frozen?\n- Confirm the platform\n## Dissent\n- Is X right?"
        c = followup.collect(evs, memo, {"alpha": "Alpha", "bravo": "Bravo"})
        qs = [x["question"] for x in c]
        self.assertEqual(qs[0], "Which Bid Whist variant is frozen?")  # memo first
        self.assertIn("Confirm the platform?", qs)
        self.assertFalse(any("Is X right" in q or "agree" in q or "ignored" in q or "POSITION" in q for q in qs))
        budget = [x for x in c if "$88" in x["question"]]
        self.assertEqual(len(budget), 1)  # near-duplicates merged with both refs kept
        self.assertEqual(budget[0]["refs"], ["E2", "E3"])
        items = followup._parse('noise [{"question": "Q?", "refs": ["E2", "bad"], "asked_by": ["Alpha"], '
                                '"suggested_answer": "Yes", "basis": "majority [E3]"}] tail')
        self.assertEqual(items[0]["refs"], ["E2"])
        self.assertEqual(items[0]["suggested"], "Yes")
        self.assertIsNone(followup._parse("no json here"))

    def _wait_end(self, rid, secs=90):
        end = time.time() + secs
        while time.time() < end and self.broker.status(rid)["live_status"] in ("RUNNING", "PAUSED", "DRAFT"):
            time.sleep(0.2)
        s = self.broker.sessions.get(rid)
        if s:
            s["thread"].join(10)

    def test_complete_saves_once_runs_round_and_replaces_only_on_change(self):
        from aesop_studio import deletion, followup
        rec = self.draft()
        project = self.svc.project(self.p["id"])
        clock = {"limit_s": 20, "reserve_s": 5, "turn_timeout": 30}
        self.assertTrue(self.broker.start(rec, project, clock=clock)["started"])
        with self.assertRaises(ValueError):  # only after the session ends
            followup.prepare(self.store, self.sup, self.broker, rec, project)
        self._wait_end(rec["id"])
        self.broker._event(rec["id"], "message", "Which storage engine should we freeze for v1?", speaker="alpha",
                           phase="exchange", names={"alpha": "Alpha"})
        d = followup.prepare(self.store, self.sup, self.broker, rec, project)
        self.assertTrue(any("storage engine" in q["question"] for q in d["questions"]))  # fallback list
        with self.assertRaises(ValueError):
            followup.complete(self.store, self.broker, rec, project, {"answers": [], "note": ""}, clock=clock)
        body = {"answers": [{"question": "Which storage engine?", "answer": "SQLite, WAL mode", "refs": ["E2", "x"]}],
                "note": "ship it"}
        r = followup.complete(self.store, self.broker, rec, project, body, clock=clock)
        self.assertFalse(r["unchanged"])
        self.assertTrue(r["round"]["started"], r["round"])
        r2_id = r["round"]["id"]
        r2 = roundtable.get(self.store, r2_id)
        self.assertEqual(r2["follow_up_of"], rec["id"])
        self.assertEqual([x["lane"] for x in r2["roster"]], [x["lane"] for x in rec["roster"]])  # same members
        self.assertIn("SQLite, WAL mode", r2["objective"])  # the owner's answers go to the speakers
        self.assertEqual(self.broker.status(rec["id"])["next_round"]["id"], r2_id)
        self._wait_end(r2_id)
        self.assertEqual(self.broker.status(r2_id)["live_status"], "COMPLETED")
        owner = [e for e in self.broker.events(rec["id"]) if e["kind"] == "owner"]
        self.assertEqual(len(owner), 1)
        self.assertEqual(owner[0]["reply_to"], ["E2"])
        # same answers again (spacing/case differ): nothing saved, no new round
        n_events = len(self.broker.events(rec["id"]))
        n_rts = self.store.one("SELECT COUNT(*) n FROM roundtables")["n"]
        same = {"answers": [{"question": "which storage engine?", "answer": "  sqlite,  WAL mode ", "refs": []}],
                "note": "Ship it"}
        r = followup.complete(self.store, self.broker, rec, project, same, clock=clock)
        self.assertTrue(r["unchanged"])
        self.assertEqual(r["round"]["id"], r2_id)
        self.assertEqual(len(self.broker.events(rec["id"])), n_events)
        self.assertEqual(self.store.one("SELECT COUNT(*) n FROM roundtables")["n"], n_rts)
        # different answers: the original note and its round are removed and replaced
        r = followup.complete(self.store, self.broker, rec, project, {"answers": [
            {"question": "Which storage engine?", "answer": "LMDB", "refs": []}]}, clock=clock)
        self.assertTrue(r["replaced"])
        self.assertEqual(r["withdrawn"], r2_id)
        self.assertIsNone(roundtable.get(self.store, r2_id))
        owner = [e for e in self.broker.events(rec["id"]) if e["kind"] == "owner"]
        self.assertEqual(len(owner), 1)
        self.assertIn("LMDB", owner[0]["content"])
        memo = self.broker.status(rec["id"])["memo"]
        self.assertEqual(memo.count("## Owner answers"), 1)
        self.assertNotIn("WAL mode", memo)
        self.assertEqual(self.store.one("SELECT COUNT(*) n FROM roundtables")["n"], n_rts)  # one round, not two
        self._wait_end(r["round"]["id"])
        d2 = followup.prepare(self.store, self.sup, self.broker, rec, project)
        self.assertEqual(d2["previous"]["answers"][0]["answer"], "LMDB")
        deletion.delete_roundtable(self.store, rec["id"])
        self.assertIsNone(self.store.one("SELECT v FROM kv WHERE k LIKE ?", (f"followup:{rec['id']}%",)))


class TestFollowUpRetry(TestFollowUp):
    def test_round_that_cannot_start_leaves_no_draft_and_complete_retries(self):
        from aesop_studio import followup
        rec = self.draft()
        project = self.svc.project(self.p["id"])
        clock = {"limit_s": 15, "reserve_s": 5, "turn_timeout": 30}
        self.assertTrue(self.broker.start(rec, project, clock=clock)["started"])
        self._wait_end(rec["id"])
        body = {"answers": [{"question": "Which engine?", "answer": "SQLite", "refs": []}]}
        keep = self.lanes
        self.lanes = keep[:2]  # two speakers short: preflight blocks the follow-up round
        r = followup.complete(self.store, self.broker, rec, project, body, clock=clock)
        self.assertFalse(r["round"]["started"])
        self.assertEqual(self.store.one("SELECT COUNT(*) n FROM roundtables")["n"], 1)  # no dead draft
        self.lanes = keep
        r = followup.complete(self.store, self.broker, rec, project, body, clock=clock)
        self.assertTrue(r["unchanged"] and r["retried"] and r["round"]["started"])
        self.assertEqual(len([e for e in self.broker.events(rec["id"]) if e["kind"] == "owner"]), 1)
        self._wait_end(r["round"]["id"])
