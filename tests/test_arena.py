"""Arena compare shell: demos, cost estimates, free-route dual-run, static fixtures."""
import http.client
import json
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

os.environ["AESOP_SIMULATED_ROUTE"] = "1"
os.environ["AESOP_PROBE_OFFLINE"] = "1"

from aesop_studio import arena  # noqa: E402
from aesop_studio.server import make_server  # noqa: E402
from aesop_studio.store import Store  # noqa: E402
from aesop_studio import providers  # noqa: E402
from aesop_studio.services import Services  # noqa: E402
from aesop_studio.tasks import Supervisor, TERMINAL  # noqa: E402


class TestArenaUnit(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-arena-"))
        self.store = Store(self.tmp / "data")
        providers.refresh(self.store)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_demo_catalog(self):
        ids = {d["id"] for d in arena.demos()}
        self.assertEqual(ids, {"alpine", "lost-valley", "deep-time", "optical"})

    def test_estimate_simulated_is_zero(self):
        est = arena.estimate(self.store, "simulated", "alpine")
        self.assertEqual(est["estimate_usd"], 0.0)
        self.assertEqual(est["estimate_kind"], "included_or_local")
        self.assertTrue(est["live_dispatch"])

    def test_lane_allows_live_dispatch_simulated(self):
        route = providers.cached(self.store)["simulated"]
        self.assertTrue(arena.lane_allows_live_dispatch(route))

    def test_lane_refuses_metered_disabled(self):
        route = {
            "id": "codex",
            "state": "READY_METERED_DISABLED",
            "billing_basis": "subscription_included",
        }
        self.assertFalse(arena.lane_allows_live_dispatch(route))

    def test_estimate_unknown_route(self):
        with self.assertRaises(ValueError):
            arena.estimate(self.store, "no-such-route", "alpine")

    def test_estimate_unknown_demo(self):
        with self.assertRaises(ValueError):
            arena.estimate(self.store, "simulated", "nope")

    def test_compare_payload_free_lanes_enables_dual(self):
        p = arena.compare_payload(self.store, "simulated", "simulated", "optical")
        self.assertTrue(p["live_dual_generation"])
        self.assertEqual(p["lanes"]["a"]["demo_id"], "optical")
        self.assertIn("free-route", p["live_note"])

    def test_metered_disabled_not_reported_as_free(self):
        """Codex CLI on API-key auth keeps billing_basis=subscription_included but state is metered."""
        routes = providers.cached(self.store)
        routes["codex"] = {
            **routes.get("codex", {}),
            "id": "codex",
            "state": "READY_METERED_DISABLED",
            "billing_basis": "subscription_included",
            "display_name": "Codex",
            "incremental_cost_status": "metered; disabled until owner sets operating limits",
        }
        self.store.x("INSERT INTO kv(k,v) VALUES('routes',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                     (json.dumps(routes),))
        est = arena.estimate(self.store, "codex", "alpine")
        self.assertNotEqual(est["estimate_kind"], "included_or_local")
        self.assertIsNone(est["estimate_usd"])
        self.assertEqual(est["estimate_kind"], "metered_unknown")
        self.assertIn("METERED", est["state"])
        self.assertFalse(est["live_dispatch"])
        cmp_ = arena.compare_payload(self.store, "simulated", "codex", "alpine")
        self.assertFalse(cmp_["live_dual_generation"])

    def test_openai_api_metered_ceiling(self):
        routes = providers.cached(self.store)
        routes["openai-api"] = {
            **routes.get("openai-api", {}),
            "id": "openai-api",
            "state": "READY_METERED_DISABLED",
            "billing_basis": "metered",
            "display_name": "Codex API",
            "incremental_cost_status": "metered; prices: test",
        }
        self.store.x("INSERT INTO kv(k,v) VALUES('routes',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                     (json.dumps(routes),))
        est = arena.estimate(self.store, "openai-api", "alpine")
        self.assertEqual(est["estimate_kind"], "metered_ceiling")
        self.assertIsInstance(est["estimate_usd"], float)
        self.assertGreater(est["estimate_usd"], 0)
        self.assertFalse(est["live_dispatch"])

    def test_run_both_simulated_ok(self):
        root = self.tmp / "proj"
        root.mkdir()
        sup = Supervisor(self.store)
        svc = Services(self.store, sup)
        p = svc.create_project("Arena", str(root), "simulated")
        before = self.store.one(
            "SELECT count(*) n FROM ledger WHERE status IN ('reserved','settled','ambiguous')")["n"]
        out = arena.run_both(self.store, svc, p["id"], "simulated", "simulated", "alpine")
        self.assertTrue(out["live_dual_generation"])
        self.assertEqual(out["lanes"]["a"]["route_id"], "simulated")
        self.assertEqual(out["lanes"]["b"]["route_id"], "simulated")
        self.assertTrue(out["lanes"]["a"]["task_id"])
        self.assertTrue(out["lanes"]["b"]["task_id"])
        # Wait for both chat tasks so ledger settles; free routes reserve $0 only.
        for side in ("a", "b"):
            tid = out["lanes"][side]["task_id"]
            end = time.time() + 20
            while time.time() < end:
                t = sup.final(tid)
                if t and t["state"] in TERMINAL:
                    break
                time.sleep(0.05)
            self.assertIn(sup.final(tid)["state"], TERMINAL)
        after = self.store.one(
            "SELECT count(*) n FROM ledger WHERE status IN ('reserved','settled','ambiguous')")["n"]
        self.assertGreaterEqual(after, before)  # included ledger rows may appear at $0
        metered = self.store.one(
            "SELECT count(*) n FROM ledger WHERE billing_basis='metered' AND reservation_usd > 0")["n"]
        self.assertEqual(metered, 0)

    def test_run_both_refuses_metered_without_reserve(self):
        root = self.tmp / "proj-m"
        root.mkdir()
        routes = providers.cached(self.store)
        routes["codex"] = {
            **routes.get("codex", {}),
            "id": "codex",
            "state": "READY_METERED_DISABLED",
            "billing_basis": "subscription_included",
            "display_name": "Codex",
            "supported_modes": ["chat", "agent"],
        }
        self.store.x("INSERT INTO kv(k,v) VALUES('routes',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                     (json.dumps(routes),))
        sup = Supervisor(self.store)
        svc = Services(self.store, sup)
        p = svc.create_project("ArenaM", str(root), "simulated")
        before = self.store.one("SELECT count(*) n FROM ledger")["n"]
        with self.assertRaises(ValueError) as ctx:
            arena.run_both(self.store, svc, p["id"], "simulated", "codex", "alpine")
        self.assertIn("Metered", str(ctx.exception))
        after = self.store.one("SELECT count(*) n FROM ledger")["n"]
        self.assertEqual(before, after)


class TestArenaHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="aesop-arena-http-"))
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        cls.port = s.getsockname()[1]
        s.close()
        cls.srv = make_server(str(cls.tmp / "data"), cls.port)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.srv.app.store.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"127.0.0.1:{self.port}"}
        h.update(headers or {})
        if "|KEY|" in h.get("Cookie", ""):
            h["Cookie"], h["X-Aesop-Key"] = h["Cookie"].split("|KEY|")
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = c.getresponse()
        return r.status, dict(r.getheaders()), r.read()

    def login(self):
        code = self.srv.app.login_code
        if not code:
            return self.__class__._cookie, self.__class__._csrf
        st, hd, _ = self.req("GET", f"/login?code={code}")
        self.assertEqual(st, 303)
        cookie = hd["Set-Cookie"].split(";")[0] + "|KEY|" + hd["Location"].split("#k=")[1]
        _, _, d = self.req("GET", "/api/session", headers={"Cookie": cookie})
        self.__class__._cookie, self.__class__._csrf = cookie, json.loads(d)["csrf"]
        return cookie, self.__class__._csrf

    def auth_headers(self, cookie, csrf, extra=None):
        h = {
            "Cookie": cookie,
            "Content-Type": "application/json",
            "Origin": f"http://127.0.0.1:{self.port}",
            "X-CSRF-Token": csrf,
        }
        if extra:
            h.update(extra)
        return h

    def test_arena_apis_and_static(self):
        cookie, csrf = self.login()
        st, _, body = self.req("GET", "/api/arena/demos", headers={"Cookie": cookie})
        self.assertEqual(st, 200)
        data = json.loads(body)
        self.assertEqual(len(data["demos"]), 4)
        self.assertTrue(data["live_dual_generation"])
        self.assertIn("free-route", data["live_note"])

        st, _, body = self.req("GET", "/api/arena/estimate?route=simulated&demo=deep-time",
                               headers={"Cookie": cookie})
        self.assertEqual(st, 200)
        est = json.loads(body)
        self.assertEqual(est["estimate_usd"], 0.0)
        self.assertEqual(est["demo_id"], "deep-time")
        self.assertTrue(est["live_dispatch"])

        st, _, body = self.req("GET", "/api/arena/compare?demo=alpine&a=simulated&b=simulated",
                               headers={"Cookie": cookie})
        self.assertEqual(st, 200)
        cmp_ = json.loads(body)
        self.assertIn("lanes", cmp_)
        self.assertTrue(cmp_["live_dual_generation"])

        st, _, body = self.req("GET", "/arena/demos.js")
        self.assertEqual(st, 200)
        self.assertIn(b"AesopArenaDemos", body)
        self.assertNotIn(b"innerHTML", body)

        st, _, body = self.req("GET", "/arena/arena.css")
        self.assertEqual(st, 200)
        self.assertIn(b".arena-split", body)
        self.assertIn(b".arena-result", body)

        st, _, html = self.req("GET", "/")
        self.assertEqual(st, 200)
        self.assertIn(b'data-tab="arena"', html)
        self.assertIn(b"/arena/demos.js", html)

        # estimate never invents a fake metered price for unknown routes
        st, _, body = self.req("GET", "/api/arena/estimate?route=missing&demo=alpine",
                               headers={"Cookie": cookie})
        self.assertEqual(st, 400)

    def test_arena_run_simulated_and_refuse_metered(self):
        cookie, csrf = self.login()
        app = self.srv.app
        root = self.tmp / "http-proj"
        root.mkdir(exist_ok=True)
        p = app.svc.create_project("ArenaHttp", str(root), "simulated")
        hdr = self.auth_headers(cookie, csrf)

        st, _, body = self.req(
            "POST", f"/api/projects/{p['id']}/arena/run",
            {"a": "simulated", "b": "simulated", "demo": "optical"}, hdr)
        self.assertEqual(st, 202, body)
        data = json.loads(body)
        self.assertTrue(data["live_dual_generation"])
        self.assertEqual(data["lanes"]["a"]["route_id"], "simulated")
        self.assertTrue(data["lanes"]["a"]["task_id"])
        self.assertTrue(data["lanes"]["b"]["task_id"])

        # Inject a metered-disabled route and refuse without growing metered ledger spend.
        routes = providers.cached(app.store)
        routes["codex"] = {
            **routes.get("codex", {}),
            "id": "codex",
            "state": "READY_METERED_DISABLED",
            "billing_basis": "subscription_included",
            "display_name": "Codex",
            "supported_modes": ["chat", "agent"],
        }
        app.store.x("INSERT INTO kv(k,v) VALUES('routes',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                    (json.dumps(routes),))
        before = app.store.one(
            "SELECT count(*) n FROM ledger WHERE billing_basis='metered' AND reservation_usd > 0")["n"]
        st, _, body = self.req(
            "POST", f"/api/projects/{p['id']}/arena/run",
            {"a": "simulated", "b": "codex", "demo": "alpine"}, hdr)
        self.assertEqual(st, 400, body)
        self.assertIn(b"Metered", body)
        after = app.store.one(
            "SELECT count(*) n FROM ledger WHERE billing_basis='metered' AND reservation_usd > 0")["n"]
        self.assertEqual(before, after)

    def test_demos_js_parses(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        import subprocess
        root = Path(__file__).resolve().parent.parent
        for rel in ("static/app.js", "static/arena/demos.js"):
            r = subprocess.run([node, "--check", str(root / rel)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{rel}: {r.stderr}")

    def test_app_js_guards_stale_arena_responses(self):
        st, _, body = self.req("GET", "/app.js")
        self.assertEqual(st, 200)
        text = body.decode("utf-8")
        self.assertIn("ARENA_PICKABLE", text)
        self.assertIn("READY_METERED_DISABLED", text)
        self.assertIn("costGen", text)
        self.assertIn("runGen", text)
        self.assertIn("arenaLaneEligible", text)
        self.assertIn("arenaRunBoth", text)
        self.assertIn("arenaStopBoth", text)
        self.assertIn("gen !== S.viewGen", text)
        # cost refresh must ignore stale success and error paths
        self.assertRegex(text, r"async function arenaRefreshCosts\(\)[\s\S]*?stale\(\)")
        self.assertRegex(text, r"catch \(e\) \{\s*if \(stale\(\)\) return;")
        # run path also guards stale replies
        self.assertRegex(text, r"async function arenaRunBoth\(\)[\s\S]*?stale\(\)")


if __name__ == "__main__":
    unittest.main()
