"""Regression tests for the verified stability/security findings fixed in the task supervisor and server."""
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ["AESOP_SIMULATED_ROUTE"] = "1"
os.environ["AESOP_PROBE_OFFLINE"] = "1"

from aesop_studio import ledger, openai_api, providers  # noqa: E402
from aesop_studio.server import App, InstanceLockError  # noqa: E402
from aesop_studio.services import Services  # noqa: E402
from aesop_studio.store import Store  # noqa: E402
from aesop_studio.tasks import CHAT_DIR_PREFIX, TERMINAL, Supervisor, diff_snapshots, snapshot  # noqa: E402


def wait(sup, tid, timeout=40):
    end = time.time() + timeout
    while time.time() < end:
        t = sup.get(tid)
        if t["state"] in TERMINAL:
            return t
        time.sleep(0.1)
    raise AssertionError(f"stuck in {sup.get(tid)['state']}")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-sup-"))
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


class TestSupervision(Base):
    @unittest.skipUnless(os.name == "nt", "simulated no-read stdin timeout is validated on Windows runners")
    def test_stdin_never_read_still_times_out(self):  # stability-01 / security-06
        os.environ["AESOP_SIM_NOREAD"] = "1"
        try:
            t0 = time.time()
            tid = self.sup.create(self.p, "simulated", "x" * (2 * 1024 * 1024), mode="chat", timeout=3)
            t = wait(self.sup, tid, 30)
        finally:
            os.environ.pop("AESOP_SIM_NOREAD", None)
        self.assertEqual(t["state"], "FAILED")
        self.assertIn("timed out", t["error"])
        self.assertLess(time.time() - t0, 20)

    def test_output_is_bounded_without_newlines(self):  # stability-08 / security-07
        t = wait(self.sup, self.sup.create(self.p, "simulated", "BIGOUT", mode="chat", timeout=60))
        size = os.path.getsize(t["output_path"])
        self.assertLess(size, 600 * 1024)
        self.assertIn("[output truncated at limit]", Path(t["output_path"]).read_text(encoding="utf-8")[-60:])

    def test_chat_sandbox_removed_and_raw_last_file_deleted(self):  # stability-17 / security-08
        t = wait(self.sup, self.sup.create(self.p, "simulated", "hello", mode="chat"))
        self.assertTrue(Path(t["cwd"]).name.startswith(CHAT_DIR_PREFIX))
        self.assertFalse(Path(t["cwd"]).exists())
        self.assertFalse(Path(t["output_path"] + ".last.txt").exists())
        self.assertIn("[REDACTED]", json.loads(t["checkpoint"])["result"])

    def test_blocked_requests_get_no_sandbox(self):  # stability-17
        t = self.sup.get(self.sup.create(self.p, "perplexity", "x", mode="chat"))
        self.assertEqual(t["state"], "BLOCKED_OWNER")
        self.assertIsNone(t["cwd"])

    def test_agent_needs_owner_acknowledgement(self):  # security-01
        self.store.x("UPDATE kv SET v='off' WHERE k=?", (f"agent_ack:{self.p['id']}",))
        t = self.sup.get(self.sup.create(self.p, "simulated", "WRITE", mode="agent"))
        self.assertEqual(t["state"], "BLOCKED_OWNER")
        self.assertIn("acknowledge", t["error"])

    def test_unresolved_effect_unknown_blocks_next_writer(self):  # stability-05
        now = time.time()
        self.store.x("INSERT INTO tasks(id,project_id,provider,prompt,state,created,checkpoint) VALUES(?,?,?,?,?,?,?)",
                     ("task_unk", self.p["id"], "simulated", "x", "EFFECT_UNKNOWN", now, json.dumps({"mode": "agent"})))
        rid = self.sup.open_repair("task_unk", "RUNNING->EFFECT_UNKNOWN", "test")
        t = self.sup.get(self.sup.create(self.p, "simulated", "WRITE", mode="agent"))
        self.assertEqual(t["state"], "BLOCKED_OWNER")
        self.sup.resolve_repair(rid, "reviewed")
        t2 = wait(self.sup, self.sup.create(self.p, "simulated", "WRITE", mode="agent"))
        self.assertEqual(t2["state"], "COMPLETED")

    def test_reconcile_sweeps_orphaned_reservations(self):  # stability-04
        now = time.time()
        self.store.x("INSERT INTO tasks(id,project_id,provider,prompt,state,created,checkpoint) VALUES(?,?,?,?,?,?,?)",
                     ("task_done", self.p["id"], "simulated", "x", "COMPLETED", now, "{}"))
        lid = ledger.reserve(self.store, "simulated", "simulated", "subscription_included", None, task_ref="task_done")
        out = self.sup.reconcile()
        self.assertTrue(any(o.get("ledger_id") == lid for o in out))
        self.assertEqual(self.store.one("SELECT status FROM ledger WHERE id=?", (lid,))["status"], "settled")

    def test_transient_error_retried_once_and_message_answered(self):
        from unittest import mock
        import aesop_studio.tasks as tasks_mod
        os.environ["AESOP_SIM_FLAKY_FILE"] = str(self.tmp / "flaky.marker")
        try:
            with mock.patch.object(tasks_mod, "RETRY_ROUTES", {"simulated"}):
                c = self.svc.new_conversation(self.p["id"])
                r = self.svc.send(self.p["id"], c["id"], "FLAKY please", [], None)
                end = time.time() + 30
                while time.time() < end:
                    m = self.svc.messages(self.p["id"], c["id"])[-1]
                    if m["status"] != "submitted":
                        break
                    time.sleep(0.2)
        finally:
            os.environ.pop("AESOP_SIM_FLAKY_FILE", None)
        self.assertEqual(m["status"], "generated", m["content"])
        first = self.sup.get(r["task_id"])
        self.assertEqual(first["state"], "FAILED")
        self.assertIn("retried automatically", first["error"])
        self.assertEqual(self.sup.final(r["task_id"])["state"], "COMPLETED")

    def test_interrupted_chat_turns_open_no_repair(self):  # health check: no noise repairs for read-only chat
        now = time.time()
        for tid, mode in (("task_chat_run", "chat"), ("task_agent_run", "agent")):
            self.store.x("INSERT INTO tasks(id,project_id,provider,prompt,state,pid,created,checkpoint) VALUES(?,?,?,?,?,?,?,?)",
                         (tid, self.p["id"], "simulated", "x", "RUNNING", 999999, now, json.dumps({"mode": mode})))
        self.sup.reconcile()
        tasks_with_repairs = {r["task_id"] for r in self.store.q("SELECT task_id FROM repairs")}
        self.assertNotIn("task_chat_run", tasks_with_repairs)
        self.assertIn("task_agent_run", tasks_with_repairs)

    def test_truncated_snapshot_reports_no_false_changes(self):  # stability-14
        before = {"a": "1", "b": "1"}
        after = {"a": "2", "c": "1"}
        d = diff_snapshots(before, after, truncated=True)
        self.assertEqual((d["added"], d["removed"], d["modified"], d["incomplete"]), ([], [], ["a"], True))

    def test_snapshot_skips_junctions(self):  # stability-13
        if os.name != "nt":
            self.skipTest("junctions are Windows-only")
        root = self.tmp / "p"
        target = self.tmp / "outside"
        target.mkdir()
        (target / "secret.txt").write_text("x", encoding="utf-8")
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "link"), str(target)], capture_output=True)
        if r.returncode != 0:
            self.skipTest("could not create a junction")
        entries, truncated = snapshot(str(root))
        self.assertFalse(any("secret.txt" in k for k in entries))


class FakeSlow(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        time.sleep(6)  # never answers within the client deadline
        try:
            self.send_response(200)
            self.end_headers()
        except OSError:
            pass


class TestApiDeadline(unittest.TestCase):  # stability-07
    @classmethod
    def setUpClass(cls):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        cls.port = s.getsockname()[1]
        s.close()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", cls.port), FakeSlow)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        os.environ["AESOP_OPENAI_TEST_BASE"] = f"http://127.0.0.1:{self.port}"
        os.environ["OPENAI_API_KEY"] = "test-key"

    def tearDown(self):
        os.environ.pop("AESOP_OPENAI_TEST_BASE", None)
        os.environ.pop("OPENAI_API_KEY", None)

    def test_overall_deadline_and_prompt_cancel(self):
        t0 = time.time()
        r = openai_api.stream("hi", "gpt-6-luna", 10, lambda d: None, threading.Event(), timeout=2)
        self.assertEqual(r["status"], "deadline")
        self.assertLess(time.time() - t0, 5)
        ev = threading.Event()
        threading.Timer(0.5, ev.set).start()
        t0 = time.time()
        r = openai_api.stream("hi", "gpt-6-luna", 10, lambda d: None, ev, timeout=30)
        self.assertEqual(r["status"], "cancelled")
        self.assertLess(time.time() - t0, 4)
        ev2 = threading.Event()
        ev2.set()
        self.assertEqual(openai_api.stream("hi", "gpt-6-luna", 10, lambda d: None, ev2, timeout=30)["status"],
                         "cancelled_presend")


class TestPersistentSessions(unittest.TestCase):  # owner: sign-in must work freely and consistently
    def test_session_survives_restart_and_file_holds_no_raw_secrets(self):
        from aesop_studio.sessions import Sessions
        d = Path(tempfile.mkdtemp(prefix="aesop-sess-"))
        s1 = Sessions(d)
        sess, csrf, key = s1.create()
        raw = (d / "sessions.json").read_text(encoding="utf-8")
        self.assertNotIn(sess, raw)
        self.assertNotIn(key, raw)
        s2 = Sessions(d)  # a restarted server
        it = s2.get(sess)
        self.assertIsNotNone(it)
        self.assertEqual(it["csrf"], csrf)
        self.assertTrue(s2.key_ok(it, key))
        self.assertFalse(s2.key_ok(it, "wrong"))
        self.assertIsNone(s2.get("not-a-session"))
        shutil.rmtree(d, ignore_errors=True)


class TestInstanceLock(unittest.TestCase):  # stability-03
    def test_second_server_refused(self):
        d = tempfile.mkdtemp(prefix="aesop-lock-")
        a = App(d, 0)
        try:
            with self.assertRaises(InstanceLockError):
                App(d, 0)
        finally:
            a.store.close()
            a._instance_lock.close()
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()


class TestAutoReverify(Base):
    def _set(self, rid, ok, age):
        import json as _j
        self.store.x("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                     (f"verify:{rid}", _j.dumps({"at": time.time() - age, "ok": ok})))

    def test_due_only_for_stale_or_failed_known_routes(self):
        self.assertEqual(providers.due_reverify(self.store), [])  # never verified: owner action
        self._set("zai", True, 3600)
        self.assertEqual(providers.due_reverify(self.store), [])  # fresh
        self._set("zai", True, providers.REVERIFY_BEFORE_S + 60)
        self.assertEqual(providers.due_reverify(self.store), ["zai"])  # about to expire
        self._set("zai", False, 60)
        self.assertEqual(providers.due_reverify(self.store), [])  # just failed: wait before re-checking
        self._set("zai", False, providers.RECHECK_FAILED_S + 60)
        self.assertEqual(providers.due_reverify(self.store), ["zai"])
