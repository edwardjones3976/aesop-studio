"""Browser drive: guards and action mapping (offline; no real Chrome, no provider calls)."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ["AESOP_SIMULATED_ROUTE"] = "1"
os.environ["AESOP_PROBE_OFFLINE"] = "1"

from aesop_studio import browse_agent, providers  # noqa: E402
from aesop_studio.services import Services  # noqa: E402
from aesop_studio.store import Store  # noqa: E402
from aesop_studio.tasks import Supervisor  # noqa: E402


class FakeBrowser:
    def __init__(self):
        self.calls = []

    def cmd(self, op, **a):
        self.calls.append((op, a))
        return {"ok": True, "url": a.get("url", "https://x/"), "title": "T", "text": "hello"}

    def shot_png(self, full=False):
        return b"\x89PNG"


class TestDrive(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-drv-"))
        (self.tmp / "p").mkdir()
        self.store = Store(self.tmp / "d")
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        providers.refresh(self.store)
        self.p = self.svc.create_project("P", str(self.tmp / "p"), "simulated")
        self.fb = FakeBrowser()
        self.d = browse_agent.Drive(self.store, self.sup, self.fb)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_start_guards(self):
        with self.assertRaises(ValueError):                       # too short a goal
            self.d.start(self.p, "claude", "x")
        with self.assertRaises(ValueError):                       # not a vision route
            self.d.start(self.p, "grok", "find the rules of bid whist")
        # vision route but file-sharing off for the project
        with mock_vision(self.d, ["claude"]):
            with self.assertRaises(ValueError) as e:
                self.d.start(self.p, "claude", "find the rules of bid whist")
            self.assertIn("off for this project", str(e.exception))

    def test_action_mapping_and_clamp(self):
        self.assertEqual(self.d._do({"action": "navigate", "url": "example.com"}), "example.com")
        self.d._do({"action": "click", "x": 99999, "y": -5})
        self.assertEqual(self.fb.calls[-1], ("click", {"x": 1366, "y": 0}))   # clamped to the viewport
        self.d._do({"action": "scroll", "dy": 400})
        self.assertEqual(self.fb.calls[-1][0], "scroll")
        self.d._do({"action": "key", "key": "Enter"})
        self.assertEqual(self.fb.calls[-1], ("key", {"key": "Enter"}))
        self.assertEqual(self.d._do({"action": "read"}), "(read the page)")
        self.d._do({"action": "type", "text": "hi"})
        self.assertTrue(self.fb.calls[-1][1].get("agent"))   # the provider's typing is flagged so passwords are refused

    def test_status_shape(self):
        st = self.d.status()
        self.assertFalse(st["active"])
        self.assertIn("vision_routes", st)


class mock_vision:  # noqa: N801 - tiny context manager
    def __init__(self, drive, routes):
        self.drive, self.routes = drive, routes

    def __enter__(self):
        self._orig = self.drive.vision_routes
        self.drive.vision_routes = lambda: self.routes

    def __exit__(self, *a):
        self.drive.vision_routes = self._orig


class TestExtensionBridgeAndSafety(unittest.TestCase):
    def setUp(self):
        from aesop_studio.browser import Browser
        self.b = Browser()

    def test_manifest_has_no_cookies_permission(self):
        import json
        manifest_path = Path(__file__).resolve().parent.parent / "extension" / "manifest.json"
        self.assertTrue(manifest_path.is_file())
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(m.get("manifest_version"), 3)
        self.assertNotIn("cookies", m.get("permissions") or [])

    def test_pairing_token_verification_and_rotation(self):
        info = self.b.pairing_info(8765)
        tok = info["pairing_token"]
        self.assertTrue(len(tok) >= 24)
        self.assertTrue(self.b.verify_token(tok))
        self.assertFalse(self.b.verify_token(""))
        self.assertFalse(self.b.verify_token("wrong-token-value"))
        new_tok = self.b.rotate_token()
        self.assertNotEqual(tok, new_tok)
        self.assertFalse(self.b.verify_token(tok))
        self.assertTrue(self.b.verify_token(new_tok))

    def test_pairing_token_persistence_across_restarts_and_rotation(self):
        from aesop_studio.browser import Browser
        td = Path(tempfile.mkdtemp(prefix="aesop-tok-"))
        try:
            b1 = Browser(td)
            tok1 = b1.pairing_token
            self.assertTrue(len(tok1) >= 24)
            self.assertIsNotNone(b1.token_path)
            self.assertTrue(b1.token_path.is_file())
            self.assertEqual(b1.token_path.read_text(encoding="utf-8").strip(), tok1)

            # Simulating Studio restart on the same data_dir preserves the exact token
            b2 = Browser(td)
            self.assertEqual(b2.pairing_token, tok1)
            self.assertTrue(b2.verify_token(tok1))

            # Rotating the token updates both memory and the persistent file
            tok_rot = b2.rotate_token()
            self.assertNotEqual(tok_rot, tok1)
            self.assertEqual(b2.token_path.read_text(encoding="utf-8").strip(), tok_rot)

            b3 = Browser(td)
            self.assertEqual(b3.pairing_token, tok_rot)
            self.assertFalse(b3.verify_token(tok1))
            self.assertTrue(b3.verify_token(tok_rot))
        finally:
            shutil.rmtree(td, ignore_errors=True)

    def test_js_pairing_security_suite(self):
        import subprocess
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node not on PATH")
        script = Path(__file__).resolve().parent / "js" / "test_pairing.mjs"
        r = subprocess.run([node_bin, str(script)], capture_output=True, text=True, timeout=15)
        self.assertEqual(r.returncode, 0, msg=f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}")

    def test_bridge_push_sanitizes_urls_secrets_and_passwords(self):
        res = self.b.bridge_push({
            "url": "https://github.com/example/repo?access_token=ghp_abcdefghijklmnopqrstuvwxyz1234",
            "title": "Repo with secret sk-proj-abcdefghijklmnopqrstu",
            "vw": 1366,
            "vh": 820,
            "headings": [{"level": 1, "text": "example/repo"}],
            "elements": [
                {"ref": 1, "role": "link", "tag": "a", "label": "Releases", "href": "https://github.com/example/repo/releases", "bbox": {"x": 100, "y": 80, "w": 90, "h": 28}},
                {"ref": 2, "role": "textbox", "tag": "input", "type": "password", "label": "Password", "value": "hunter2secret", "is_password": True, "bbox": {"x": 200, "y": 200, "w": 180, "h": 32}},
                {"ref": 3, "role": "checkbox", "tag": "div", "label": "I am not a robot reCAPTCHA", "is_captcha": True, "bbox": {"x": 200, "y": 260, "w": 180, "h": 40}},
                {"ref": 4, "role": "button", "tag": "button", "label": "Place order & Buy now", "is_purchase": True, "bbox": {"x": 200, "y": 330, "w": 160, "h": 36}},
            ],
            "main_text": "Release notes key=sk-proj-abcdefghijklmnopqrstu",
            "text": "Release notes key=sk-proj-abcdefghijklmnopqrstu",
            "tabs": [{"id": 10, "title": "example/repo", "url": "https://github.com/example/repo?token=secret99", "selected": True}],
        })
        self.assertTrue(res["ok"])
        self.assertTrue(self.b.extension_connected())
        self.assertEqual(self.b.mode(), "extension")
        st = self.b.live_state()
        self.assertNotIn("ghp_abcdef", st["url"])
        self.assertNotIn("sk-proj-abcdef", st["title"])
        self.assertNotIn("sk-proj-abcdef", st["main_text"])
        self.assertNotIn("secret99", st["tabs"][0]["url"])
        pw_el = [e for e in st["elements"] if e["ref"] == 2][0]
        self.assertEqual(pw_el["value"], "[password field]")
        self.assertNotIn("hunter2secret", str(st))

    def test_agent_safety_refuses_passwords_captchas_and_purchases(self):
        self.test_bridge_push_sanitizes_urls_secrets_and_passwords()
        # Refused by #ref for password, captcha, and purchase elements
        for ref, word in ((2, "password"), (3, "CAPTCHA"), (4, "purchase")):
            r = self.b.cmd("click_ref", ref=ref, agent=True)
            self.assertFalse(r["ok"])
            self.assertIn(word, r["error"])
        r_fill = self.b.cmd("fill_ref", ref=2, text="secret", agent=True)
        self.assertFalse(r_fill["ok"])
        self.assertIn("password", r_fill["error"])
        # Refused by bounding-box coordinates when agent clicks inside a protected element
        r_xy_pw = self.b.cmd("click", x=220, y=210, agent=True)
        self.assertFalse(r_xy_pw["ok"])
        self.assertIn("password", r_xy_pw["error"])
        r_xy_cap = self.b.cmd("click", x=220, y=275, agent=True)
        self.assertFalse(r_xy_cap["ok"])
        self.assertIn("CAPTCHA", r_xy_cap["error"])
        r_xy_buy = self.b.cmd("click", x=220, y=345, agent=True)
        self.assertFalse(r_xy_buy["ok"])
        self.assertIn("purchase", r_xy_buy["error"])

    def test_bridge_command_poll_and_reply_roundtrip(self):
        import threading
        self.b.bridge_push({"url": "https://example.org/", "title": "Example", "elements": [{"ref": 1, "role": "link", "label": "More", "bbox": {"x": 10, "y": 10, "w": 50, "h": 20}}]})

        def ext_worker():
            polled = self.b.bridge_poll(wait_s=2.0)
            cmd = polled.get("cmd")
            if cmd:
                self.b.bridge_reply(cmd["id"], {
                    "ok": True,
                    "url": "https://example.org/more",
                    "title": "More Info",
                    "main_text": "Detailed specification v2.4.0",
                    "text": "Detailed specification v2.4.0",
                    "elements": [{"ref": 1, "role": "heading", "label": "Spec v2.4.0", "bbox": {"x": 10, "y": 10, "w": 100, "h": 24}}],
                })

        t = threading.Thread(target=ext_worker, daemon=True)
        t.start()
        out = self.b.cmd("click_ref", ref=1, agent=True)
        t.join(timeout=3)
        self.assertTrue(out["ok"])
        self.assertEqual(out["url"], "https://example.org/more")
        self.assertEqual(self.b.live_state()["title"], "More Info")


class SmartFakeBrowser:
    """Simulates a multi-page GitHub repository in Extension mode with full DOM + Accessibility snapshots."""
    def __init__(self):
        self.calls = []
        self.url = "https://example.org/"
        self.title = "Start"

    def snapshot(self):
        if "releases" in self.url:
            return {
                "ok": True,
                "url": self.url,
                "title": "Releases · example/aesop",
                "vw": 1366,
                "vh": 820,
                "headings": [{"level": 1, "text": "Releases"}, {"level": 2, "text": "v2.4.0 — Browser v2 Extension Bridge"}],
                "elements": [
                    {"ref": 1, "role": "link", "tag": "a", "label": "v2.4.0 — Browser v2 Extension Bridge", "href": "https://github.com/example/aesop/releases/tag/v2.4.0", "bbox": {"x": 40, "y": 120, "w": 280, "h": 28}},
                ],
                "forms": [],
                "links": [{"text": "v2.4.0", "href": "https://github.com/example/aesop/releases/tag/v2.4.0"}],
                "main_text": "Release v2.4.0 (latest): Adds Manifest V3 Chrome Extension bridge and DOM-first agent with notebook citations.",
                "text": "Release v2.4.0 (latest): Adds Manifest V3 Chrome Extension bridge and DOM-first agent with notebook citations.",
                "tabs": [{"id": 1, "title": "Releases · example/aesop", "url": self.url, "selected": True}],
            }
        return {
            "ok": True,
            "url": self.url,
            "title": "example/aesop: Local-first AI studio",
            "vw": 1366,
            "vh": 820,
            "headings": [{"level": 1, "text": "example/aesop"}],
            "elements": [
                {"ref": 1, "role": "link", "tag": "a", "label": "Code", "href": "https://github.com/example/aesop", "bbox": {"x": 20, "y": 60, "w": 60, "h": 24}},
                {"ref": 2, "role": "link", "tag": "a", "label": "Releases (v2.4.0)", "href": "https://github.com/example/aesop/releases", "bbox": {"x": 900, "y": 180, "w": 140, "h": 28}},
            ],
            "forms": [],
            "links": [{"text": "Releases (v2.4.0)", "href": "https://github.com/example/aesop/releases"}],
            "main_text": "example/aesop repository overview. Latest release is v2.4.0.",
            "text": "example/aesop repository overview. Latest release is v2.4.0.",
            "tabs": [{"id": 1, "title": "example/aesop", "url": self.url, "selected": True}],
        }

    def cmd(self, op, **a):
        self.calls.append((op, a))
        if op == "navigate":
            self.url = a.get("url") or self.url
        elif op == "click_ref" and int(a.get("ref") or 0) == 2:
            self.url = "https://github.com/example/aesop/releases"
        elif op == "find":
            snap = self.snapshot()
            return {
                **snap,
                "query": a.get("query", ""),
                "matches": [{"line": 1, "snippet": "Release v2.4.0 (latest): Adds Manifest V3 Chrome Extension bridge"}],
                "element_matches": snap["elements"],
            }
        return self.snapshot()

    def shot_png(self, full=False):
        raise AssertionError("DOM-first agent should not capture screenshots when structured DOM elements are present")


class TestDomFirstAgent5Step(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-dom5-"))
        (self.tmp / "p").mkdir()
        self.store = Store(self.tmp / "d")
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        providers.refresh(self.store)
        self.p = self.svc.create_project("P", str(self.tmp / "p"), "simulated")
        self.p = self.svc.update_project(self.p["id"], {"transfer_policy": {"simulated": True}})
        self.sb = SmartFakeBrowser()
        self.d = browse_agent.Drive(self.store, self.sup, self.sb)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_five_step_github_release_summary_to_notebook(self):
        import json
        import time
        scripted_steps = [
            {"thought": "Open the repository page", "action": "navigate", "url": "https://github.com/example/aesop"},
            {"thought": "Click the Releases link [#2]", "action": "click_ref", "ref": 2},
            {"thought": "Search for v2.4.0 release details", "action": "find", "query": "v2.4.0"},
            {
                "thought": "Cite the latest release into the project Research Notebook",
                "action": "cite_notebook",
                "claim": "Latest release v2.4.0 adds the Manifest V3 Chrome Extension bridge and DOM-first browsing agent.",
                "locator": "Releases · v2.4.0",
            },
            {
                "thought": "Goal complete",
                "action": "done",
                "answer": "The latest release of example/aesop is v2.4.0, which adds the Manifest V3 Chrome Extension bridge and DOM-first agent. Cited into the Research Notebook.",
            },
        ]
        prompts_seen = []

        def fake_ask(run, snap, shot_path=None):
            idx = len(prompts_seen)
            prompts_seen.append(browse_agent.format_snapshot_for_prompt(snap, run.get("last_find")))
            self.assertIsNone(shot_path)
            return dict(scripted_steps[min(idx, len(scripted_steps) - 1)])

        self.d._ask = fake_ask
        self.d.STEP_PAUSE = 0.01
        st = self.d.start(
            self.p,
            "simulated",
            "open the GitHub repo example/aesop, find the latest release, and summarize it into the notebook",
            max_steps=6,
        )
        deadline = time.time() + 5.0
        while time.time() < deadline:
            cur = self.d.status()
            if not cur["active"]:
                break
            time.sleep(0.02)
        final = self.d.status()
        self.assertFalse(final["active"])
        self.assertEqual(len(final["steps"]), 5)
        self.assertEqual([s["action"] for s in final["steps"]], ["navigate", "click_ref", "find", "cite_notebook", "done"])
        self.assertIn("v2.4.0", final["answer"])
        self.assertIsNotNone(final.get("cited"))
        # Verify the provider received structured DOM/Accessibility trees
        self.assertIn("INTERACTIVE ELEMENTS", prompts_seen[0])
        self.assertIn("OUTLINE (HEADINGS)", prompts_seen[1])
        # Verify the Research Notebook has the read source and cited finding
        sources = self.store.q("SELECT * FROM sources WHERE project_id=?", (self.p["id"],))
        findings = self.store.q("SELECT * FROM findings WHERE project_id=?", (self.p["id"],))
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["status"], "read")
        self.assertEqual(sources[0]["locator"], "https://github.com/example/aesop/releases")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["status"], "cited")
        self.assertIn("v2.4.0", findings[0]["claim"])


class TestBrowserHttpRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import socket
        import threading
        from aesop_studio.server import make_server
        cls.tmp = Path(tempfile.mkdtemp(prefix="aesop-brhttp-"))
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
        try:
            cls.srv.app._instance_lock.close()
        except Exception:
            pass
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def req(self, method, path, body=None, headers=None):
        import http.client
        import json
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"127.0.0.1:{self.port}"}
        h.update(headers or {})
        if "|KEY|" in h.get("Cookie", ""):
            h["Cookie"], h["X-Aesop-Key"] = h["Cookie"].split("|KEY|")
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, dict(r.getheaders()), data

    def login(self):
        import json
        code = self.srv.app.login_code
        if not code:
            return self.__class__._cookie, self.__class__._csrf
        st, hd, _ = self.req("GET", f"/login?code={code}")
        self.assertEqual(st, 303)
        cookie = hd["Set-Cookie"].split(";")[0] + "|KEY|" + hd["Location"].split("#k=")[1]
        _, _, d = self.req("GET", "/api/session", headers={"Cookie": cookie})
        self.__class__._cookie, self.__class__._csrf = cookie, json.loads(d)["csrf"]
        return cookie, self.__class__._csrf

    def test_bridge_requires_pairing_token_and_blocks_web_origins(self):
        import json
        cookie, csrf = self.login()
        # Unauthenticated localhost caller without X-Aesop-Bridge-Token is rejected with 403
        st, _, _ = self.req("POST", "/api/browser/bridge/push", {"url": "https://x.org"})
        self.assertEqual(st, 403)
        st, _, _ = self.req("GET", "/api/browser/bridge/poll?wait=0.02")
        self.assertEqual(st, 403)
        # Wrong token is rejected with 403
        st, _, _ = self.req("POST", "/api/browser/bridge/push", {"url": "https://x.org"}, {"X-Aesop-Bridge-Token": "bad"})
        self.assertEqual(st, 403)
        # Fetch the real pairing token from authenticated Studio session
        st, _, raw = self.req("GET", "/api/browser/pairing", headers={"Cookie": cookie})
        self.assertEqual(st, 200)
        tok = json.loads(raw)["pairing_token"]
        self.assertTrue(self.srv.app.browser.token_path.is_file())
        self.assertEqual(self.srv.app.browser.token_path.read_text(encoding="utf-8").strip(), tok)
        # Rotate via HTTP endpoint and verify persistence to disk
        st, _, raw_rot = self.req("POST", "/api/browser/pairing/rotate", {}, {
            "Cookie": cookie,
            "Origin": f"http://127.0.0.1:{self.port}",
            "X-CSRF-Token": csrf,
            "Content-Type": "application/json",
        })
        self.assertEqual(st, 200)
        tok = json.loads(raw_rot)["pairing_token"]
        self.assertEqual(self.srv.app.browser.token_path.read_text(encoding="utf-8").strip(), tok)
        # External web Origin is rejected even if token were known
        st, _, _ = self.req("POST", "/api/browser/bridge/push", {"url": "https://x.org"}, {
            "X-Aesop-Bridge-Token": tok,
            "Origin": "https://evil.example.com",
        })
        self.assertEqual(st, 403)
        # Valid extension push with X-Aesop-Bridge-Token succeeds
        st, _, raw = self.req("POST", "/api/browser/bridge/push", {
            "url": "https://github.com/example/aesop",
            "title": "example/aesop",
            "main_text": "Aesop Studio v2 browser documentation",
            "text": "Aesop Studio v2 browser documentation",
            "headings": [{"level": 1, "text": "Aesop Studio"}],
            "elements": [{"ref": 1, "role": "link", "label": "Docs", "bbox": {"x": 20, "y": 20, "w": 60, "h": 24}}],
        }, {"X-Aesop-Bridge-Token": tok, "Origin": "chrome-extension://abcdefghijklmnop"})
        self.assertEqual(st, 200)
        # Studio live state and cite endpoint work end-to-end
        st, _, raw = self.req("GET", "/api/browser/state", headers={"Cookie": cookie})
        self.assertEqual(st, 200)
        state = json.loads(raw)
        self.assertTrue(state["connected"])
        self.assertEqual(state["mode"], "extension")
        self.assertEqual(state["title"], "example/aesop")
        # Create a project and cite the browser page into its Research Notebook
        root = self.tmp / "projcite"
        root.mkdir(exist_ok=True)
        p = self.srv.app.svc.create_project("CiteProj", str(root), "simulated")
        st, _, raw = self.req("POST", f"/api/projects/{p['id']}/browser/cite", {
            "claim": "Aesop Studio v2 uses a Manifest V3 Chrome Extension paired via X-Aesop-Bridge-Token.",
            "locator": "README · Browser v2",
        }, {"Cookie": cookie, "Origin": f"http://127.0.0.1:{self.port}", "X-CSRF-Token": csrf, "Content-Type": "application/json"})
        self.assertEqual(st, 201)
        cited = json.loads(raw)
        self.assertEqual(cited["source"]["status"], "read")
        self.assertEqual(cited["finding"]["status"], "cited")


if __name__ == "__main__":
    unittest.main()
