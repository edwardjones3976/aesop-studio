"""Perplexity/Firecrawl chat routes (network mocked) and file/folder attachments in chat."""
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ["AESOP_SIMULATED_ROUTE"] = "1"
os.environ["AESOP_PROBE_OFFLINE"] = "1"

from aesop_studio import ledger, providers, research_routes, researcher  # noqa: E402
from aesop_studio.services import FILE_BUDGET, Services, _clean_rel_name  # noqa: E402
from aesop_studio.store import Store  # noqa: E402
from aesop_studio.tasks import TERMINAL, Supervisor  # noqa: E402


def fake_post(url, body, key):
    if url.endswith("/v2/search"):
        return {"success": True, "data": {"web": [{"url": "https://ex.org/a", "title": "A", "description": "alpha"}]}}
    if url.endswith("/v2/scrape"):
        return {"data": {"markdown": "[Home](/)\n\n# Page\nBody with [a link](https://x).", "metadata": {"title": "Page"}}}
    if url.endswith("/chat/completions"):
        assert body["messages"][-1]["role"] == "user"
        return {"choices": [{"message": {"content": "Answer [1]."}}], "citations": ["https://ex.org/src"],
                "usage": {"prompt_tokens": 40, "completion_tokens": 20, "total_tokens": 60,
                          "cost": {"total_cost": 0.0061}}}
    raise AssertionError(url)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-rf-"))
        (self.tmp / "p").mkdir()
        self.store = Store(self.tmp / "d")
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        self.p = self.svc.create_project("P", str(self.tmp / "p"), "simulated")
        self.c = self.svc.new_conversation(self.p["id"])

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def wait(self, tid):
        end = time.time() + 20
        while self.sup.get(tid)["state"] not in TERMINAL and time.time() < end:
            time.sleep(0.05)
        return self.sup.get(tid)


class TestResearchRoutes(Base):
    def setUp(self):
        super().setUp()
        self.keys = mock.patch.object(research_routes, "status", lambda: {"firecrawl": True, "perplexity": True})
        self.keys.start()
        # build the two routes as a machine with both keys would see them
        routes = providers.refresh(self.store)
        for rid in ("firecrawl", "perplexity"):
            r = routes[rid]
            r["state"] = "READY_INCLUDED" if rid == "firecrawl" else "READY_METERED_DISABLED"
        import json
        self.store.x("UPDATE kv SET v=? WHERE k='routes'", (json.dumps(routes),))
        self.post = mock.patch.object(researcher, "_post", fake_post)
        self.post.start()
        self.key = mock.patch.object(research_routes, "key", lambda rid: "test-key")
        self.key.start()

    def tearDown(self):
        self.post.stop()
        self.key.stop()
        self.keys.stop()
        super().tearDown()

    def test_firecrawl_search_and_page_read(self):
        r = self.svc.send(self.p["id"], self.c["id"], "who makes A?", [], "firecrawl", confirm_switch=True)
        t = self.wait(r["task_id"])
        self.assertEqual(t["state"], "COMPLETED", t["error"])
        self.assertIn("https://ex.org/a", self.sup.output(t["id"])[0])
        r = self.svc.send(self.p["id"], self.c["id"], "read https://ex.org/page please", [], "firecrawl", confirm_switch=True)
        out = self.sup.output(self.wait(r["task_id"])["id"])[0]
        self.assertIn("# Page", out)
        self.assertIn("Body with a link.", out)  # link text kept, URL and menu line dropped
        self.assertNotIn("[Home]", out)
        row = self.store.one("SELECT * FROM ledger WHERE task_ref=?", (r["task_id"],))
        self.assertEqual(row["billing_basis"], "subscription_included")

    def test_perplexity_metered_with_citations_and_context(self):
        r = self.svc.send(self.p["id"], self.c["id"], "q1", [], "perplexity", confirm_switch=True)
        self.assertEqual(self.wait(r["task_id"])["state"], "BLOCKED_OWNER")  # no spend envelope yet
        ledger.set_permit(self.store, True)
        r = self.svc.send(self.p["id"], self.c["id"], "what is new?", [], "perplexity", confirm_switch=True)
        t = self.wait(r["task_id"])
        self.assertEqual(t["state"], "COMPLETED", t["error"])
        out = self.sup.output(t["id"])[0]
        self.assertIn("Answer [1].", out)
        self.assertIn("[1] https://ex.org/src", out)
        row = self.store.one("SELECT * FROM ledger WHERE task_ref=?", (t["id"],))
        self.assertEqual(row["provider"], "perplexity")
        self.assertAlmostEqual(row["settled_usd"], 0.0061)
        ctx = self.svc.build_context(self.p["id"], self.c["id"], "follow-up?", [], "perplexity")
        self.assertIn("Perplexity (Sonar) receives", ctx)
        with self.assertRaises(ledger.BudgetError):  # still no other metered biller
            ledger.reserve(self.store, "anthropic", "x", "metered", 0.01)

    def test_research_routes_refuse_files(self):
        a = self.svc.attach(self.p["id"], "n.md", b"# hi")
        with self.assertRaises(ValueError) as e:
            self.svc.build_context(self.p["id"], self.c["id"], "x", [a["id"]], "firecrawl")
        self.assertIn("questions and links", str(e.exception))

    def test_perplexity_messages_alternate(self):
        msgs = research_routes.perplexity_messages([{"role": "assistant", "content": "a0"}, {"role": "user", "content": "u1"},
                                                    {"role": "user", "content": "u2"}, {"role": "assistant", "content": "a2"}], "q")
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user"])
        self.assertTrue(msgs[0]["content"].startswith("u1\n\nu2"))


class TestFilesAndFolders(Base):
    def test_folder_paths_budget_and_secret_files(self):
        self.svc.update_project(self.p["id"], {"transfer_policy": {"simulated": True, "grok": True}})
        self.assertEqual(_clean_rel_name("C:/proj/../src/app.py"), "proj/src/app.py")
        ids = [self.svc.attach(self.p["id"], f"app/src/f{i}.py", (f"# file {i}\n" + "x" * 9000).encode())["id"] for i in range(5)]
        env = self.svc.attach(self.p["id"], "app/.env", b"KEY=secret")
        self.assertEqual(env["extract_status"], "unsupported")
        ctx = self.svc.build_context(self.p["id"], self.c["id"], "review", ids, "simulated")
        self.assertIn('<file name="app/src/f0.py"', ctx)
        self.assertIn("[5 files attached:", ctx)
        small = self.svc.build_context(self.p["id"], self.c["id"], "review", ids, "grok")
        self.assertLess(len(small), FILE_BUDGET["grok"] + 3000)  # fair shares inside the argv-prompt room
        self.assertIn('truncated="', small)
        with self.assertRaises(ValueError):
            self.svc.build_context(self.p["id"], self.c["id"], "x", [env["id"]], "simulated")

    def test_discard_unsent_only(self):
        a = self.svc.attach(self.p["id"], "a.md", b"# a")
        b = self.svc.attach(self.p["id"], "b.md", b"# b")
        self.svc.update_project(self.p["id"], {"transfer_policy": {"simulated": True}})
        r = self.svc.send(self.p["id"], self.c["id"], "use b", [b["id"]], None)
        self.wait(r["task_id"])
        self.assertTrue(self.svc.discard_unsent(a["id"])["deleted"])
        self.assertFalse(self.svc.discard_unsent(b["id"])["deleted"])  # already sent: kept with the message


if __name__ == "__main__":
    unittest.main()


class TestHandoff(Base):
    def test_switch_needs_no_confirm_and_next_provider_gets_labelled_history(self):
        r = self.svc.send(self.p["id"], self.c["id"], "the code word is ORANGE-7", [], "simulated")
        self.wait(r["task_id"])
        self.svc.messages(self.p["id"], self.c["id"])  # files the finished answer into the conversation
        # pretend an earlier answer came from Codex, then hand over to another provider
        self.store.x("UPDATE messages SET provider='codex' WHERE role='assistant'")
        ctx = self.svc.build_context(self.p["id"], self.c["id"], "what was the code word?", [], "simulated")
        self.assertIn("[assistant · Codex]", ctx)
        self.assertIn("taking over this conversation from Codex", ctx)
        self.assertIn("ORANGE-7", ctx)
        # the same provider continuing gets no takeover note
        self.store.x("UPDATE messages SET provider='simulated' WHERE role='assistant'")
        self.assertNotIn("[handoff:", self.svc.build_context(self.p["id"], self.c["id"], "again?", [], "simulated"))
        # a project whose default is another (even unusable) provider still sends without a confirm step
        self.svc.update_project(self.p["id"], {"provider_default": "perplexity"})
        r = self.svc.send(self.p["id"], self.c["id"], "continue", [], "simulated")
        self.assertEqual(self.wait(r["task_id"])["state"], "COMPLETED")

    def test_history_window_is_bounded_and_says_what_it_left_out(self):
        for i in range(40):
            self.store.x("INSERT INTO messages(id,conversation_id,role,content,status,provider,created,meta) VALUES(?,?,?,?,?,?,?,?)",
                         (f"m{i}", self.c["id"], "user" if i % 2 == 0 else "assistant", f"turn {i} " + "x" * 3000,
                          "saved" if i % 2 == 0 else "generated", None if i % 2 == 0 else "codex", 1000 + i, "{}"))
        ctx = self.svc.build_context(self.p["id"], self.c["id"], "next", [], "grok")
        self.assertIn("older message(s) not shown", ctx)
        self.assertIn("turn 39", ctx)       # the newest turns are the ones kept
        self.assertNotIn("turn 0 ", ctx)
        self.assertLess(len(ctx), 24_000)   # fits Grok's argv-prompt limit


class TestRedo(Base):
    def _answer(self, text, route="simulated"):
        r = self.svc.send(self.p["id"], self.c["id"], text, [], route)
        self.wait(r["task_id"])
        return [m for m in self.svc.messages(self.p["id"], self.c["id"]) if m["id"] == r["message_id"]][0]

    def test_retry_failed_regenerate_latest_edit_latest(self):
        bad = self._answer("first question", route="grok")    # Grok can't run in tests: the answer fails
        self.assertEqual(bad["status"], "failed")
        r = self.svc.redo(self.p["id"], self.c["id"], bad["id"], "simulated", None)
        self.assertEqual(r["message_id"], bad["id"])           # replaced in place, no duplicate answer
        prompt = self.sup.get(r["task_id"])["prompt"]
        self.assertNotIn("Request failed", prompt)             # the failed attempt is not in the context
        self.assertEqual(prompt.count("first question"), 1)    # the question appears once, not twice
        self.wait(r["task_id"])
        n = len(self.svc.messages(self.p["id"], self.c["id"]))
        good = self._answer("second question")
        self.assertEqual(good["status"], "generated")
        with self.assertRaises(ValueError):                    # an older good answer can't be regenerated
            msgs = self.svc.messages(self.p["id"], self.c["id"])
            self.svc.redo(self.p["id"], self.c["id"], msgs[1]["id"], None, None)
        r = self.svc.redo(self.p["id"], self.c["id"], good["id"], None, None)     # regenerate the latest
        self.assertIn("second question", self.sup.get(r["task_id"])["prompt"])
        self.wait(r["task_id"])
        user = [m for m in self.svc.messages(self.p["id"], self.c["id"]) if m["role"] == "user"]
        r = self.svc.redo(self.p["id"], self.c["id"], user[-1]["id"], None, "second question, edited")
        self.assertIn("second question, edited", self.sup.get(r["task_id"])["prompt"])
        self.wait(r["task_id"])
        msgs = self.svc.messages(self.p["id"], self.c["id"])
        self.assertEqual(len(msgs), n + 2)                     # still one question + one answer per exchange
        self.assertEqual([m for m in msgs if m["role"] == "user"][-1]["content"], "second question, edited")
        with self.assertRaises(ValueError):                    # only the most recent message can be edited
            self.svc.redo(self.p["id"], self.c["id"], user[0]["id"], None, "rewrite history")

    def test_cannot_redo_while_waiting(self):
        r = self.svc.send(self.p["id"], self.c["id"], "SLEEP a while", [], "simulated")
        from aesop_studio.services import Conflict
        with self.assertRaises(Conflict):
            self.svc.redo(self.p["id"], self.c["id"], r["message_id"], None, None)
        self.sup.cancel(r["task_id"])
        self.wait(r["task_id"])


class TestPageWall(unittest.TestCase):
    def test_wall_detection(self):
        from aesop_studio.research_routes import _page_wall
        gh = _page_wall("https://github.com/edwardjones3976/long-table-bid-whist",
                        {"statusCode": 404, "title": "Page not found · GitHub"}, "You signed in with another tab")
        self.assertIn("HTTP 404", gh)
        self.assertIn("private or non-existent GitHub", gh)
        self.assertIsNone(_page_wall("https://ex.org/a", {"statusCode": 200, "title": "Real"}, "x" * 2000))
        wall = _page_wall("https://n.site/x", {"title": "Sign in to continue"}, "Sign in to continue reading")
        self.assertIn("not readable content", wall)


class TestBrowserManager(unittest.TestCase):
    def test_profile_under_data_dir_and_signin_blocks(self):
        import tempfile
        import types
        from aesop_studio import browser
        d = tempfile.mkdtemp()
        b = browser.Browser(d)
        self.assertTrue(b.profile.endswith("browser-profile"))
        self.assertFalse(b.status()["signing_in"])
        b.signin_proc = types.SimpleNamespace(poll=lambda: None)  # pretend a sign-in window is open
        self.assertTrue(b.signing_in())
        with self.assertRaises(RuntimeError) as e:
            b.cmd("ping", timeout=2)
        self.assertIn("signing in", str(e.exception))

    def test_use_my_chrome_paths(self):
        import tempfile
        from pathlib import Path
        from aesop_studio import browser
        b = browser.Browser(tempfile.mkdtemp())
        orig = (browser.chrome_exe, browser._port_open, browser._chrome_running)
        try:
            browser.chrome_exe = lambda: None
            with self.assertRaises(RuntimeError):
                b.use_my_chrome()
            browser.chrome_exe = lambda: Path("C:/chrome.exe")
            browser._port_open = lambda port: True           # already listening -> connect
            self.assertTrue(b.use_my_chrome()["connected"])
            self.assertEqual(b.mode, "chrome")
            self.assertTrue(b.status()["chrome_connected"])
            b.use_studio_chrome()
            self.assertEqual(b.mode, "studio")
            browser._port_open = lambda port: False
            browser._chrome_running = lambda: True           # running, no port, no confirm -> ask to restart
            self.assertTrue(b.use_my_chrome(confirm_restart=False).get("needs_restart"))
            self.assertEqual(b.mode, "studio")               # nothing restarted without confirmation
        finally:
            browser.chrome_exe, browser._port_open, browser._chrome_running = orig

    def test_status_shape_and_unavailable_note(self):
        from aesop_studio import browser
        b = browser.Browser()
        st = b.status()
        self.assertEqual(set(st) >= {"available", "running", "url", "title", "note", "mode", "chrome_found"}, True)
        self.assertFalse(st["running"])
        # when no venv python exists, cmd fails cleanly rather than hanging
        orig = browser.venv_python
        browser.venv_python = lambda: None
        try:
            self.assertFalse(b.available())
            with self.assertRaises(RuntimeError):
                b.cmd("ping", timeout=2)
        finally:
            browser.venv_python = orig
