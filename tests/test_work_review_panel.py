"""Work chat messages mount review panels before DOM attach; panel must still fetch review."""

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

from aesop_studio.server import make_server  # noqa: E402
from aesop_studio.tasks import TERMINAL  # noqa: E402


class TestWorkReviewPanelMount(unittest.TestCase):
    def test_review_panel_source_waits_for_dom_connection(self):
        app_js = Path(__file__).resolve().parent.parent / "static" / "app.js"
        chunk = app_js.read_text(encoding="utf-8")
        start = chunk.index("function reviewPanel")
        body = chunk[start : start + 1400]
        self.assertIn("detachWaits", body)
        self.assertNotIn("if (!box.isConnected) return stop();", body)

    def test_work_review_open_task_selects_fix_task_in_inspector(self):
        app_js = Path(__file__).resolve().parent.parent / "static" / "app.js"
        chunk = app_js.read_text(encoding="utf-8")
        self.assertIn(
            'const openFixTask = (id) => { S.taskSel = id; setItab("changes"); renderInspector(); };',
            chunk,
        )
        self.assertIn("reviewPanel(meta.task_id, box, openFixTask, rv)", chunk)

    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError:
            cls._playwright = None
            return
        cls._playwright = sync_playwright
        cls.tmp = Path(tempfile.mkdtemp(prefix="aesop-rv-"))
        cls.proj = cls.tmp / "proj"
        cls.proj.mkdir()
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        cls.port = s.getsockname()[1]
        s.close()
        cls.srv = make_server(str(cls.tmp / "data"), cls.port)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "srv", None):
            cls.srv.shutdown()
            cls.srv.server_close()
            cls.srv.app.store.close()
        if getattr(cls, "tmp", None):
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_work_message_issues_review_fetch_after_mount(self):
        if not self._playwright:
            self.skipTest("playwright not installed")
        app = self.srv.app
        p = app.svc.create_project("R", str(self.proj), "simulated")
        app.store.x("INSERT INTO kv(k,v) VALUES(?, 'on')", (f"agent_ack:{p['id']}",))
        app.svc.update_project(p["id"], {"transfer_policy": {"simulated": True}})
        c = app.svc.new_conversation(p["id"])
        r = app.svc.send(p["id"], c["id"], "WRITE a note", [], None, work=True)
        end = time.time() + 30
        while app.sup.get(r["task_id"])["state"] not in TERMINAL and time.time() < end:
            time.sleep(0.05)
        tid = r["task_id"]
        code = app.login_code
        base = f"http://127.0.0.1:{self.port}"
        review_urls = []

        with self._playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page()
            page.on(
                "request",
                lambda req: (
                    review_urls.append(req.url)
                    if f"/api/tasks/{tid}/review" in req.url
                    else None
                ),
            )
            page.goto(f"{base}/login?code={code}")
            page.wait_for_timeout(800)
            page.goto(f"{base}/")
            page.wait_for_timeout(500)
            page.evaluate(
                """async ([pid, cid]) => {
                  const s = await (await fetch('/api/session')).json();
                  const H = {'Content-Type': 'application/json', 'X-CSRF-Token': s.csrf, 'X-Aesop-Key': localStorage.getItem('aesop.key') || ''};
                  await fetch('/api/projects/' + pid, {method: 'PATCH', headers: H, body: JSON.stringify({last_conversation_id: cid})});
                  localStorage.setItem('aesop.project', pid);
                  localStorage.setItem('aesop.tab.' + pid, 'chat');
                }""",
                [p["id"], c["id"]],
            )
            page.reload()
            page.wait_for_timeout(2500)
            browser.close()

        self.assertTrue(
            any(f"/api/tasks/{tid}/review" in u for u in review_urls),
            f"expected review fetch for task {tid}, saw: {review_urls[:5]}",
        )


if __name__ == "__main__":
    unittest.main()
