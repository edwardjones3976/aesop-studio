"""Live-verified CLI routes (Cursor first): honest probe states, honest War Room lanes, and blob consistency.

Regression for 2026-11-10: the War Room showed Cursor as "INSTALLED_UNVERIFIED · official CLI (not integrated) ·
no verified in-app conversation adapter" when its 7-day live verification had simply expired.
"""
import json
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
from aesop_studio.services import Services  # noqa: E402
from aesop_studio.store import Store  # noqa: E402
from aesop_studio.tasks import TERMINAL, Supervisor  # noqa: E402

DAY = 24 * 3600


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-rv-"))
        (self.tmp / "p").mkdir()
        self.store = Store(self.tmp / "d")
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        providers.refresh(self.store)
        self.p = self.svc.create_project("P", str(self.tmp / "p"), "simulated")

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def record(self, rid, ok, age, **extra):
        self.store.x("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                     (f"verify:{rid}", json.dumps({"at": time.time() - age, "ok": ok, **extra})))

    def probe_cursor(self, status=(0, "Logged in as someone"), cmd=("node", "index.js")):
        """Run the real probe with every external CLI/loopback stubbed; only cursor is 'installed'."""
        def run(argv, timeout=30):
            return status if argv[-1] == "status" else (0, "2026.10.22-27dcf5f")
        none = lambda: None  # noqa: E731
        with mock.patch.dict(os.environ, {"AESOP_PROBE_OFFLINE": "0"}), \
                mock.patch.object(providers, "_cursor_cmd", lambda: list(cmd) if cmd else None), \
                mock.patch.object(providers, "_codex_cmd", none), mock.patch.object(providers, "_claude_cmd", none), \
                mock.patch.object(providers, "_agy_cmd", none), mock.patch.object(providers, "_copilot_cmd", none), \
                mock.patch.object(providers, "_grok_cmd", none), mock.patch.object(providers, "_zai_cmd", none), \
                mock.patch.object(providers, "_local_models", lambda *a: None), \
                mock.patch("aesop_studio.research_routes.status",
                           lambda: {"firecrawl": False, "perplexity": False}), \
                mock.patch("aesop_studio.research_routes.key_problem", lambda *a: None), \
                mock.patch.object(providers, "_run", side_effect=run):
            return providers.probe(self.store)["cursor"]

    def seed_routes(self, **cursor):
        """Cached routes blob as the War Room reads it: codex + claude ready, cursor as given."""
        routes = providers.cached(self.store)
        for rid in ("codex", "claude"):
            routes[rid].update(state="READY_INCLUDED", billing_basis="subscription_included")
        routes["cursor"].update(cursor)
        self.store.x("UPDATE kv SET v=? WHERE k='routes'", (json.dumps(routes),))


class TestProbeStates(Base):
    def test_never_verified(self):
        r = self.probe_cursor()
        self.assertEqual(r["state"], "UNVERIFIED")
        self.assertIn("never verified", r["evidence"])
        self.assertEqual(r["next_step"], "verify")
        self.assertIsNone(r["last_verified_at"])  # no fake "verified just now"
        self.assertTrue(r["installed"] and r["verifiable"])

    def test_fresh_ok_is_ready(self):
        self.record("cursor", True, 3600, detail="reply matched")
        r = self.probe_cursor()
        self.assertEqual(r["state"], "READY_INCLUDED")
        self.assertIsNone(r["next_step"])

    def test_expired_says_expired_and_keeps_dates(self):
        self.record("cursor", True, 18 * DAY)
        r = self.probe_cursor()
        self.assertEqual(r["state"], "UNVERIFIED")
        self.assertIn("expired", r["evidence"])
        self.assertNotIn("never verified", r["evidence"])
        self.assertAlmostEqual(r["verified_at"], time.time() - 18 * DAY, delta=60)
        self.assertAlmostEqual(r["verify_expires_at"], r["verified_at"] + providers.VERIFY_MAX_AGE_S, delta=1)
        self.assertEqual(r["last_verified_at"], r["verified_at"])

    def test_fresh_failure_is_unavailable(self):
        self.record("cursor", False, 60, detail="You've hit your usage limit")
        r = self.probe_cursor()
        self.assertEqual(r["state"], "UNAVAILABLE")
        self.assertEqual(r["next_step"], "verify")
        self.assertIn("usage limit", r["evidence"])

    def test_not_logged_in_is_not_mistaken_for_logged_in(self):
        self.record("cursor", True, 3600)
        r = self.probe_cursor(status=(0, "Not logged in"))
        self.assertEqual(r["state"], "AUTH_REQUIRED")
        self.assertEqual(r["next_step"], "login")

    def test_status_timeout_is_not_a_sign_out(self):
        r = self.probe_cursor(status=(-1, "timed out after 40s "))
        self.assertEqual(r["state"], "UNVERIFIED")
        self.assertEqual(r["next_step"], "recheck")
        self.assertEqual(r["auth_status"], "unknown")

    def test_cli_not_found(self):
        r = self.probe_cursor(cmd=None)
        self.assertEqual(r["state"], "UNAVAILABLE")
        self.assertFalse(r["installed"])
        self.assertEqual(r["next_step"], "install")

    def test_verify_detail_prefers_the_quota_line(self):
        out = "Thinking...\nError: You've hit your usage limit for this model\nexit\n"
        self.assertIn("usage limit", providers._verify_detail(out, 1))
        self.assertEqual(providers._verify_detail("", 2), "exit 2")
        self.assertEqual(providers._verify_detail("a\nb", 1), "b")


class TestWarRoomLane(Base):
    def lane(self, **cursor):
        self.seed_routes(**cursor)
        with mock.patch.object(lanes, "_find", return_value=None), \
                mock.patch.object(lanes, "_secret_store_names", return_value=[]):
            d = lanes.discover(self.store)
        return d, next(l for l in d["lanes"] if l["id"] == "cursor")

    def expired(self):
        at = time.time() - 18 * DAY
        return {"state": "UNVERIFIED", "installed": True, "verifiable": True, "next_step": "verify",
                "verified_at": at, "verify_ok": True, "verify_expires_at": at + providers.VERIFY_MAX_AGE_S,
                "supported_modes": ["chat"],
                "evidence": "live verification expired …; run Verify (one minimal live call) to enable"}

    def test_expired_cursor_tells_the_truth_and_offers_verify(self):
        _, l = self.lane(**self.expired())
        self.assertEqual(l["readiness"], "INSTALLED_UNVERIFIED")
        self.assertFalse(l["counts_as_speaker"])
        self.assertFalse(any("adapter" in r for r in l["reasons"]))
        self.assertIn("verification expired", l["reasons"][0])
        self.assertTrue(l["reasons"][0].startswith("Cursor:"))
        self.assertEqual(l["next_action"], {"kind": "verify", "route_id": "cursor"})
        self.assertEqual(l["route_type"], "official CLI · verification needed")
        self.assertEqual(l["conversation_support"], "route_not_ready")
        self.assertNotIn("not integrated", l["route_type"])

    def test_signed_out_and_timeout_and_failed(self):
        _, l = self.lane(state="AUTH_REQUIRED", installed=True, verifiable=True, next_step="login",
                         supported_modes=["chat"], evidence="cursor-agent status: not signed in")
        self.assertEqual(l["next_action"]["kind"], "login")
        self.assertEqual(l["route_type"], "official CLI · sign-in needed")
        _, l = self.lane(state="UNVERIFIED", installed=True, verifiable=True, next_step="recheck",
                         supported_modes=["chat"], evidence="cursor-agent status timed out")
        self.assertEqual(l["next_action"]["kind"], "recheck")
        _, l = self.lane(state="UNAVAILABLE", installed=True, verifiable=True, next_step="verify", verify_ok=False,
                         verified_at=time.time() - 60, supported_modes=["chat"],
                         evidence="last live verification failed: You've hit your usage limit")
        self.assertEqual(l["next_action"]["kind"], "verify")
        self.assertIn("last verification failed", l["reasons"][0])
        self.assertNotIn("usage limit", " ".join(l["reasons"]))  # raw output stays out of exportable reasons
        self.assertIn("usage limit", l["route_status"][0]["evidence"])  # but is shown with the route

    def test_not_installed_anywhere_is_not_detected(self):
        _, l = self.lane(state="UNAVAILABLE", installed=False, next_step="install",
                         evidence="cursor CLI not found on this PC")
        self.assertEqual(l["readiness"], "NOT_DETECTED")
        self.assertIsNone(l["next_action"])

    def test_war_room_preflight_names_the_cause(self):
        d, _ = self.lane(**self.expired())
        rec = roundtable.save(self.store, self.p["id"], {
            "mode": "war_room", "objective": "Design review of the card game", "deliverable": "memo",
            "time_limit_min": 8, "response_window_s": 30, "roster": list(lanes.ADMINS), "sharing_ack": True})
        pf = roundtable.preflight(self.store, rec, d)
        checks = {c["id"]: c for c in pf["checks"]}
        self.assertFalse(checks["admin_ready"]["pass"])
        self.assertIn("Codex: ready.", checks["admin_ready"]["detail"])
        self.assertIn("Cursor: verification expired", checks["admin_ready"]["detail"])
        self.assertEqual(checks["funding"]["detail"], "no verified route/funding: Cursor")
        # once verified, the same draft passes both checks
        self.seed_routes(state="READY_INCLUDED", next_step=None)
        with mock.patch.object(lanes, "_find", return_value=None), \
                mock.patch.object(lanes, "_secret_store_names", return_value=[]):
            pf = roundtable.preflight(self.store, rec)
        checks = {c["id"]: c["pass"] for c in pf["checks"]}
        self.assertTrue(checks["admin_ready"] and checks["funding"])

    def test_export_packet_keeps_route_evidence_out(self):
        self.seed_routes(**self.expired())
        rec = roundtable.save(self.store, self.p["id"], {
            "mode": "war_room", "objective": "Design review of the card game", "deliverable": "memo",
            "time_limit_min": 8, "response_window_s": 30, "roster": list(lanes.ADMINS), "sharing_ack": True})
        packet = roundtable.export_packet(self.store, rec, self.p)
        self.assertTrue(all("route_status" not in l for l in packet["lanes_at_export"]))


class TestTaskKeepsBlobInStep(Base):
    def test_successful_call_updates_cached_route(self):
        routes = providers.cached(self.store)
        old = time.time() - 3 * DAY
        routes["simulated"].update(state="READY_INCLUDED", last_verified_at=old, evidence="old")
        self.store.x("UPDATE kv SET v=? WHERE k='routes'", (json.dumps(routes),))
        with mock.patch.object(providers, "LIVE_VERIFY_ROUTES", providers.LIVE_VERIFY_ROUTES | {"simulated"}):
            tid = self.sup.create(self.p, "simulated", "hello", mode="chat")
            end = time.time() + 40
            while self.sup.get(tid)["state"] not in TERMINAL and time.time() < end:
                time.sleep(0.1)
        self.assertEqual(self.sup.get(tid)["state"], "COMPLETED")
        r = json.loads(self.store.one("SELECT v FROM kv WHERE k='routes'")["v"])["simulated"]
        rec = json.loads(self.store.one("SELECT v FROM kv WHERE k='verify:simulated'")["v"])
        self.assertEqual(r["last_verified_at"], rec["at"])
        self.assertIn("successful request", r["evidence"])
        self.assertEqual(rec["source"], "task")


if __name__ == "__main__":
    unittest.main()
