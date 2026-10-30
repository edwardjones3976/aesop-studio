"""Plan tab: checklist CRUD, build items that follow their task, AI draft, activity feed (simulated route)."""
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

os.environ["AESOP_SIMULATED_ROUTE"] = "1"
os.environ["AESOP_PROBE_OFFLINE"] = "1"

from aesop_studio import plan, providers  # noqa: E402
from aesop_studio.services import Services  # noqa: E402
from aesop_studio.store import Store  # noqa: E402
from aesop_studio.tasks import TERMINAL, Supervisor  # noqa: E402


class TestPlan(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-plan-"))
        (self.tmp / "p").mkdir()
        self.store = Store(self.tmp / "d")
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        providers.refresh(self.store)
        self.p = self.svc.create_project("P", str(self.tmp / "p"), "simulated")
        self.store.x("INSERT INTO kv(k,v) VALUES(?, 'on')", (f"agent_ack:{self.p['id']}",))

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_crud_and_order(self):
        pid = self.p["id"]
        a = plan.add(self.store, pid, "first step")
        b = plan.add(self.store, pid, "second step")
        items = plan.list_items(self.store, self.sup, pid)
        self.assertEqual([i["id"] for i in items], [a["id"], b["id"]])
        plan.update(self.store, pid, a["id"], status="doing")
        plan.update(self.store, pid, b["id"], status="done")
        plan.update(self.store, pid, b["id"], content="second step, renamed")
        items = plan.list_items(self.store, self.sup, pid)
        self.assertEqual(items[0]["status"], "doing")
        self.assertEqual(items[1]["content"], "second step, renamed")
        self.assertEqual(plan.clear_done(self.store, pid)["cleared"], 1)
        self.assertTrue(plan.remove(self.store, pid, a["id"])["deleted"])
        self.assertEqual(plan.list_items(self.store, self.sup, pid), [])
        with self.assertRaises(ValueError):
            plan.add(self.store, pid, "x")
        c = plan.add(self.store, pid, "ok item")
        with self.assertRaises(ValueError):
            plan.update(self.store, pid, c["id"], status="sideways")
        with self.assertRaises(KeyError):
            plan.update(self.store, pid, "pln_nope", status="done")

    def test_build_item_follows_its_task(self):
        pid = self.p["id"]
        tid = self.sup.create(self.p, "simulated", "WRITE a small helper file for scoring", mode="agent", timeout=30)
        it = plan.add_for_task(self.store, pid, tid, "WRITE a small helper file for scoring")
        self.assertEqual(it["status"], "doing")
        self.assertTrue(it["content"].startswith("Work: WRITE a small helper"))
        end = time.time() + 30
        while time.time() < end and self.sup.get(tid)["state"] not in TERMINAL:
            time.sleep(0.2)
        items = plan.list_items(self.store, self.sup, pid)   # reading refreshes from the task record
        self.assertEqual(items[0]["status"], "done")
        # owner can override an auto item; it then stops following the task
        plan.update(self.store, pid, it["id"], status="todo")
        self.assertEqual(plan.list_items(self.store, self.sup, pid)[0]["status"], "todo")

    def test_draft_adds_new_steps_only(self):
        pid = self.p["id"]
        plan.add(self.store, pid, "Wire the scoring table")  # already planned: the draft must not duplicate it
        c = self.svc.new_conversation(pid)
        self.store.x("INSERT INTO messages(id,conversation_id,role,content,status,provider,created,meta) "
                     "VALUES('m1',?,?,?,?,NULL,1,'{}')", (c["id"], "user", "let's plan the bid whist engine", "saved"))
        out = plan.draft(self.store, self.sup, self.svc, pid)
        self.assertEqual([i["content"] for i in out["added"]], ["Add renege detection"])
        items = plan.list_items(self.store, self.sup, pid)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[1]["source"], "Simulated (test only)")

    def test_plans_are_per_project_and_focus_is_not_shared(self):
        other_root = self.tmp / "q"
        other_root.mkdir()
        q = self.svc.create_project("Q", str(other_root), "simulated")
        plan.add(self.store, self.p["id"], "only in P")
        plan.set_focus(self.store, self.p["id"], "Bid whist scoring")
        plan.add(self.store, q["id"], "only in Q")
        plan.set_focus(self.store, q["id"], "Unrelated other game")
        p_items = [i["content"] for i in plan.list_items(self.store, self.sup, self.p["id"])]
        q_items = [i["content"] for i in plan.list_items(self.store, self.sup, q["id"])]
        self.assertEqual(p_items, ["only in P"])
        self.assertEqual(q_items, ["only in Q"])
        pay_p = plan.payload(self.store, self.sup, self.p["id"], self.p["name"])
        pay_q = plan.payload(self.store, self.sup, q["id"], q["name"])
        self.assertEqual(pay_p["project_id"], self.p["id"])
        self.assertEqual(pay_q["project_id"], q["id"])
        self.assertEqual(pay_p["focus"], "Bid whist scoring")
        self.assertEqual(pay_q["focus"], "Unrelated other game")
        self.assertNotEqual(pay_p["focus"], pay_q["focus"])

    def test_activity_feed_reads_events(self):
        pid = self.p["id"]
        self.store.event("build_tests", pid, state="PASSED", summary="all 4 passed")
        self.store.event("team_review", pid, reviewer="claude", state="DONE", verdict="approve")
        self.store.event("something_new", pid, x=1)
        acts = plan.activity(self.store, pid)
        texts = [a["text"] for a in acts]
        self.assertIn("Tests after build: passed — all 4 passed", texts)
        self.assertTrue(any("Claude Code reviewed a build: approve" in t for t in texts))
        self.assertIn("something new", texts)  # unknown kinds degrade to readable words


if __name__ == "__main__":
    unittest.main()


class TestTypingCorpus(TestPlan):
    def test_corpus_is_owner_messages_only_dedup_newest_first(self):
        pid = self.p["id"]
        c = self.svc.new_conversation(pid)
        rows = [("u1", "user", "What do you think about the bidding engine design?", "saved", 1),
                ("a1", "assistant", "An answer that must never be suggested back", "generated", 2),
                ("u2", "user", "what do you think about the bidding engine design?", "saved", 3),  # dup, case-insens
                ("u3", "user", "Fix the renege detection in scoring.py", "saved", 4),
                ("u4", "user", "short", "saved", 5)]  # under 8 chars: dropped
        for mid, role, content, status, t in rows:
            self.store.x("INSERT INTO messages(id,conversation_id,role,content,status,provider,created,meta) "
                         "VALUES(?,?,?,?,?,NULL,?, '{}')", (mid, c["id"], role, content, status, t))
        texts = self.svc.typing_corpus(pid)
        self.assertEqual(texts, ["Fix the renege detection in scoring.py",
                                 "what do you think about the bidding engine design?"])


class TestNewProjectFolders(TestPlan):
    def test_create_missing_makes_one_level_and_refuses_bad_roots(self):
        base = self.tmp / "work"
        base.mkdir()
        p = self.svc.create_project("Bid Whist VR", str(base / "Bid Whist VR"), "simulated", create_missing=True)
        self.assertTrue((base / "Bid Whist VR").is_dir())
        self.assertEqual(Path(p["root"]).name, "Bid Whist VR")
        with self.assertRaises(ValueError):   # parent missing: nothing is created
            self.svc.create_project("X", str(self.tmp / "nope" / "deeper"), "simulated", create_missing=True)
        self.assertFalse((self.tmp / "nope").exists())
        with self.assertRaises(Exception):    # a refused root is removed again after being made
            self.svc.create_project("Home", str(Path.home() / ".ssh" / "zz-aesop-test"), "simulated", create_missing=True)
        self.assertFalse((Path.home() / ".ssh" / "zz-aesop-test").exists())
        with self.assertRaises(Exception):    # without the flag, a missing folder is still refused
            self.svc.create_project("Y", str(base / "missing"), "simulated")

    def test_folder_suggestions(self):
        base = self.tmp / "look"
        for n in ("alpha", "alps", "beta", ".hidden", "$sys"):
            (base / n).mkdir(parents=True)
        (base / "alpha.txt").write_text("not a dir", encoding="utf-8")
        r = self.svc.folder_suggestions(str(base / "al"))
        self.assertEqual([Path(x).name for x in r["dirs"]], ["alpha", "alps"])
        self.assertFalse(r["exists"]); self.assertTrue(r["parent_exists"])
        r = self.svc.folder_suggestions(f"{base}{os.sep}")
        self.assertEqual([Path(x).name for x in r["dirs"]], ["alpha", "alps", "beta"])  # hidden/system skipped
        self.assertTrue(self.svc.folder_suggestions(str(base / "alpha"))["exists"])
        self.assertEqual(self.svc.folder_suggestions("relative/path")["dirs"], [])
        starters = self.svc.folder_suggestions("")["dirs"]
        self.assertTrue(all(Path(x).is_dir() for x in starters))
        norm = {str(Path(x).resolve()) for x in starters}
        self.assertIn(str(Path(self.tmp).resolve()), norm)  # parent of this test's own project is offered first
