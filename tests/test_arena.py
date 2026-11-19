"""Arena compare shell: demos catalog, cost estimates, static fixtures (no live dispatch)."""
import http.client
import json
import os
import shutil
import socket
import tempfile
import threading
import unittest
from pathlib import Path

os.environ["AESOP_SIMULATED_ROUTE"] = "1"
os.environ["AESOP_PROBE_OFFLINE"] = "1"

from aesop_studio import arena  # noqa: E402
from aesop_studio.server import make_server  # noqa: E402
from aesop_studio.store import Store  # noqa: E402
from aesop_studio import providers  # noqa: E402


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
        self.assertFalse(est["live_dispatch"])

    def test_estimate_unknown_route(self):
        with self.assertRaises(ValueError):
            arena.estimate(self.store, "no-such-route", "alpine")

    def test_estimate_unknown_demo(self):
        with self.assertRaises(ValueError):
            arena.estimate(self.store, "simulated", "nope")

    def test_compare_payload(self):
        p = arena.compare_payload(self.store, "simulated", "simulated", "optical")
        self.assertFalse(p["live_dual_generation"])
        self.assertEqual(p["lanes"]["a"]["demo_id"], "optical")
        self.assertIn("v1", p["live_note"])


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

    def req(self, method, path, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"127.0.0.1:{self.port}"}
        h.update(headers or {})
        if "|KEY|" in h.get("Cookie", ""):
            h["Cookie"], h["X-Aesop-Key"] = h["Cookie"].split("|KEY|")
        c.request(method, path, headers=h)
        r = c.getresponse()
        return r.status, dict(r.getheaders()), r.read()

    def login(self):
        code = self.srv.app.login_code
        if not code:
            return self.__class__._cookie
        st, hd, _ = self.req("GET", f"/login?code={code}")
        self.assertEqual(st, 303)
        cookie = hd["Set-Cookie"].split(";")[0] + "|KEY|" + hd["Location"].split("#k=")[1]
        self.__class__._cookie = cookie
        return cookie

    def test_arena_apis_and_static(self):
        cookie = self.login()
        st, _, body = self.req("GET", "/api/arena/demos", headers={"Cookie": cookie})
        self.assertEqual(st, 200)
        data = json.loads(body)
        self.assertEqual(len(data["demos"]), 4)
        self.assertFalse(data["live_dual_generation"])

        st, _, body = self.req("GET", "/api/arena/estimate?route=simulated&demo=deep-time",
                               headers={"Cookie": cookie})
        self.assertEqual(st, 200)
        est = json.loads(body)
        self.assertEqual(est["estimate_usd"], 0.0)
        self.assertEqual(est["demo_id"], "deep-time")

        st, _, body = self.req("GET", "/api/arena/compare?demo=alpine&a=simulated&b=simulated",
                               headers={"Cookie": cookie})
        self.assertEqual(st, 200)
        cmp_ = json.loads(body)
        self.assertIn("lanes", cmp_)

        st, _, body = self.req("GET", "/arena/demos.js")
        self.assertEqual(st, 200)
        self.assertIn(b"AesopArenaDemos", body)
        self.assertNotIn(b"innerHTML", body)

        st, _, body = self.req("GET", "/arena/arena.css")
        self.assertEqual(st, 200)
        self.assertIn(b".arena-split", body)

        st, _, html = self.req("GET", "/")
        self.assertEqual(st, 200)
        self.assertIn(b'data-tab="arena"', html)
        self.assertIn(b"/arena/demos.js", html)

        # estimate never invents a fake metered price for unknown routes
        st, _, body = self.req("GET", "/api/arena/estimate?route=missing&demo=alpine",
                               headers={"Cookie": cookie})
        self.assertEqual(st, 400)

    def test_demos_js_parses(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        import subprocess
        root = Path(__file__).resolve().parent.parent
        for rel in ("static/app.js", "static/arena/demos.js"):
            r = subprocess.run([node, "--check", str(root / rel)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{rel}: {r.stderr}")


if __name__ == "__main__":
    unittest.main()
