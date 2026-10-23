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
