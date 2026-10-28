"""Offline tests. The SIMULATED route is an adapter simulation and never counts as a live provider."""

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
os.environ["AESOP_PROBE_OFFLINE"] = "1"  # never launch real provider CLIs in tests

from aesop_studio import backup, ledger  # noqa: E402
from aesop_studio.security import (
    ScopeError,
    contained_path,
    extract,
    redact,
    safe_fetch,
    FetchError,
)  # noqa: E402
from aesop_studio.server import make_server  # noqa: E402
from aesop_studio.services import Conflict, Services  # noqa: E402
from aesop_studio.store import Store  # noqa: E402
from aesop_studio.tasks import Supervisor, TERMINAL  # noqa: E402


def wait_state(sup, tid, states=TERMINAL, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        t = sup.get(tid)
        if t["state"] in states:
            return t
        time.sleep(0.1)
    raise AssertionError(f"task stuck in {sup.get(tid)['state']}")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-test-"))
        self.root = self.tmp / "proj"
        self.root.mkdir()
        self.store = Store(self.tmp / "data")
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        from aesop_studio import providers

        providers.refresh(self.store)
        self.p = self.svc.create_project("Demo", str(self.root), "simulated")
        self.store.x(
            "INSERT INTO kv(k,v) VALUES(?, 'on')", (f"agent_ack:{self.p['id']}",)
        )

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestDefaultTransferPolicy(Base):
    def test_new_project_allows_in_app_routes_not_research(self):
        from aesop_studio import providers

        fresh_root = self.tmp / "fresh"
        fresh_root.mkdir()
        p = self.svc.create_project("Fresh", str(fresh_root), "simulated")
        pol = p["transfer_policy"]
        self.assertTrue(pol.get("simulated"))
        routes = providers.cached(self.store)
        for rid, r in routes.items():
            if r.get("transport") == "research":
                self.assertNotIn(rid, pol)
            else:
                self.assertTrue(pol.get(rid), rid)


class TestWorkflow(Base):
    def test_ac01_chat_save_restart_resume(self):
        a = self.svc.attach(
            self.p["id"], "notes.md", b"# Synthetic\nThe launch code is AURORA."
        )
        self.assertEqual(a["extract_status"], "extracted")
        c = self.svc.new_conversation(self.p["id"])
        self.svc.update_project(self.p["id"], {"transfer_policy": {"simulated": False}})
        with self.assertRaises(PermissionError):
            self.svc.send(self.p["id"], c["id"], "summarize", [a["id"]], None)
        self.svc.update_project(self.p["id"], {"transfer_policy": {"simulated": True}})
        r = self.svc.send(self.p["id"], c["id"], "summarize", [a["id"]], None)
        wait_state(self.sup, r["task_id"])
        msgs = self.svc.messages(self.p["id"], c["id"])
        self.assertEqual(msgs[-1]["status"], "generated")
        self.assertIn("[REDACTED]", msgs[-1]["content"])  # provider output is redacted
        self.svc.save_artifact(
            self.p["id"], "chat_answer", "t", msgs[-1]["content"], msgs[-1]["id"]
        )
        # restart: new store/services on the same data dir
        self.store.close()
        s2 = Store(self.tmp / "data")
        svc2 = Services(s2, Supervisor(s2))
        self.assertEqual(len(svc2.messages(self.p["id"], c["id"])), 2)
        self.assertEqual(len(svc2.artifacts(self.p["id"])), 1)
        s2.close()

    def test_preview_cannot_read_other_project_conversation(self):
        other_root = self.tmp / "o"
        other_root.mkdir()
        other = self.svc.create_project("O", str(other_root), "simulated")
        oc = self.svc.new_conversation(other["id"])
        with self.assertRaises(KeyError):
            self.svc.build_context(self.p["id"], oc["id"], "x", [], "simulated")

    def test_chat_work_edits_project_folder(self):
        self.svc.update_project(self.p["id"], {"transfer_policy": {"simulated": True}})
        c = self.svc.new_conversation(self.p["id"])
        r = self.svc.send(
            self.p["id"], c["id"], "WRITE a file from chat", [], "simulated", work=True
        )
        self.assertTrue(r["work"])
        t = wait_state(self.sup, r["task_id"])
        self.assertEqual(t["state"], "COMPLETED")
        self.assertIn("sim_output.txt", json.loads(t["changed_files"])["added"])
        msgs = self.svc.messages(self.p["id"], c["id"])
        self.assertTrue(msgs[0]["meta"].get("work"))
        self.assertTrue(msgs[-1]["meta"].get("work"))
        self.assertEqual(msgs[-1]["status"], "generated")
        r2 = self.svc.redo(self.p["id"], c["id"], msgs[-1]["id"])
        self.assertTrue(r2["work"])
        t2 = wait_state(self.sup, r2["task_id"])
        self.assertEqual(t2["state"], "COMPLETED")
        self.assertEqual(json.loads(t2["checkpoint"])["mode"], "agent")
        chat = self.svc.send(self.p["id"], c["id"], "just a question", [], "simulated")
        self.assertFalse(chat["work"])
        wait_state(self.sup, chat["task_id"])
        self.assertNotIn("work", self.svc.messages(self.p["id"], c["id"])[-1]["meta"])

    def test_projects_survive_a_restart_of_the_same_library(self):
        self.assertEqual(self.svc.last_project(), self.p["id"])
        self.svc.archive_project(self.p["id"])
        self.assertEqual(self.svc.last_project(), "")
        other = self.tmp / "kept"
        other.mkdir()
        kept = self.svc.create_project("Kept", str(other), "simulated")
        self.store.close()
        s2 = Store(self.tmp / "data")
        svc2 = Services(s2, Supervisor(s2))
        ids = [p["id"] for p in svc2.projects()]
        self.assertIn(kept["id"], ids)
        self.assertNotIn(self.p["id"], ids)
        self.assertEqual(svc2.last_project(), kept["id"])
        s2.close()

    def test_ac02_explicit_provider_pick_is_enough(self):
        # owner rule 2026-10-23: switching provider mid-chat is the point of Studio; the composer pick needs no confirm
        c = self.svc.new_conversation(self.p["id"])
        r = self.svc.send(self.p["id"], c["id"], "hi", [], "codex")
        self.assertTrue(r["task_id"])

    def test_unsupported_files_honest(self):
        self.assertEqual(extract("a.pdf", b"%PDF-1.4 /Encrypt")[0], "encrypted")
        self.assertEqual(extract("a.docx", b"PK")[0], "unsupported")
        self.assertEqual(extract("a.txt", b"\xff\xfe\x00bad")[0], "malformed")
        self.assertEqual(extract("a.txt", b"x" * (6 * 1024 * 1024))[0], "too_large")


class TestAgent(Base):
    def test_ac03_agent_run_and_changed_files(self):
        tid = self.sup.create(self.p, "simulated", "WRITE a file", mode="agent")
        t = wait_state(self.sup, tid)
        self.assertEqual(t["state"], "COMPLETED")
        self.assertIn("sim_output.txt", json.loads(t["changed_files"])["added"])

    @unittest.skipUnless(
        os.name == "nt", "process-tree cancel uses Windows Job Objects / taskkill"
    )
    def test_ac03_cancel_kills_owned_tree(self):
        tid = self.sup.create(self.p, "simulated", "SLEEP", mode="agent")
        wait_state(self.sup, tid, {"RUNNING"})
        time.sleep(0.5)
        pid = self.sup.get(tid)["pid"]
        second = self.sup.get(self.sup.create(self.p, "simulated", "x", mode="agent"))
        self.assertEqual(second["state"], "BLOCKED_OWNER")  # one writer per project
        self.assertTrue(self.sup.cancel(tid))
        t = wait_state(self.sup, tid)
        self.assertEqual(t["state"], "CANCELLED")
        from aesop_studio.tasks import pid_alive

        self.assertFalse(pid_alive(pid))

    @unittest.skipUnless(
        os.name == "nt", "ORPHAN/job-object grandchild cleanup is Windows-specific"
    )
    def test_detached_descendant_terminated_via_job(self):
        import re
        from aesop_studio.tasks import pid_alive

        start = time.time()
        tid = self.sup.create(self.p, "simulated", "ORPHAN", mode="agent")
        t = wait_state(self.sup, tid, timeout=40)
        self.assertLess(time.time() - start, 30)  # did not wait for the 120s grandchild
        out, _ = self.sup.output(tid)
        gpid = int(re.search(r"grandchild (\d+)", out).group(1))
        self.assertFalse(pid_alive(gpid))
        if os.name == "nt":
            self.assertEqual(t["state"], "COMPLETED")
            self.assertIn("job object", t["error"])

    def test_failure_recorded(self):
        t = wait_state(
            self.sup, self.sup.create(self.p, "simulated", "FAIL", mode="agent")
        )
        self.assertEqual(t["state"], "FAILED")
        self.assertEqual(t["exit_code"], 3)

    def test_unusable_route_blocked(self):
        t = self.sup.get(self.sup.create(self.p, "perplexity", "x", mode="agent"))
        self.assertEqual(t["state"], "BLOCKED_OWNER")

    def test_ac04_restart_reconciliation_no_replay(self):
        now = time.time()
        for tid, st, pid in (
            ("task_a", "RUNNING", 999999),
            ("task_b", "RESERVED", None),
        ):
            self.store.x(
                "INSERT INTO tasks(id,project_id,provider,prompt,state,pid,created,checkpoint) VALUES(?,?,?,?,?,?,?,?)",
                (tid, self.p["id"], "simulated", "x", st, pid, now, "{}"),
            )
        out = {o["task_id"]: o["to"] for o in Supervisor(self.store).reconcile()}
        self.assertEqual(out, {"task_a": "INTERRUPTED", "task_b": "INTERRUPTED"})
        rep = self.store.q("SELECT * FROM repairs WHERE task_id='task_a'")
        self.assertEqual(len(rep), 1)
        pkt = json.loads(
            Supervisor(self.store)
            .export_repair(rep[0]["id"])
            .read_text(encoding="utf-8")
        )
        for k in (
            "failure_signature",
            "reproducer",
            "affected_contract",
            "allowed_paths",
            "required_tests",
            "scope",
            "budget_usd",
            "rollback",
            "owner",
        ):
            self.assertIn(k, pkt)
        self.assertEqual(
            self.store.one("SELECT status FROM repairs WHERE id=?", (rep[0]["id"],))[
                "status"
            ],
            "EXPORTED_FOR_FOREMAN",
        )
        self.assertEqual(
            self.store.one("SELECT count(*) n FROM tasks WHERE state='RUNNING'")["n"], 0
        )


class TestResearchMemory(Base):
    def test_ac05_local_citations_and_export(self):
        a = self.svc.attach(
            self.p["id"], "synthetic.txt", b"Synthetic study: widgets improved 3%."
        )
        s = self.svc.add_local_source(self.p["id"], a["id"])
        f = self.svc.add_finding(self.p["id"], "Widgets improved 3%", s["id"], "line 1")
        self.assertEqual(f["status"], "cited")
        self.assertEqual(
            self.svc.add_finding(self.p["id"], "Unsupported claim", None, "")["status"],
            "unsupported",
        )
        pub = self.svc.export_notebook(self.p["id"], include_private=False)
        self.assertNotIn("Widgets improved", pub)  # private source not leaked
        self.assertIn(
            "Widgets improved",
            self.svc.export_notebook(self.p["id"], include_private=True),
        )

    def test_ac06_memory_isolation_and_correction(self):
        other_root = self.tmp / "other"
        other_root.mkdir()
        other = self.svc.create_project("Other", str(other_root), "simulated")
        m = self.svc.add_memory(
            other["id"], "authoritative", "note", "SECRET-OTHER", []
        )
        self.assertFalse(
            any("SECRET-OTHER" in x["content"] for x in self.svc.memory(self.p["id"]))
        )
        self.assertEqual(self.svc.search(self.p["id"], "SECRET-OTHER"), [])
        with self.assertRaises(KeyError):
            self.svc.correct_memory(self.p["id"], m["id"], "x")
        with self.assertRaises(ValueError):
            self.svc.add_memory(self.p["id"], "derived", "summary", "no sources", [])
        mine = self.svc.add_memory(
            self.p["id"], "derived", "summary", "Old summary", ["att_x"]
        )
        new = self.svc.correct_memory(self.p["id"], mine["id"], "Corrected")
        states = {x["id"]: x["status"] for x in self.svc.memory(self.p["id"])}
        self.assertEqual(states[mine["id"]], "superseded")
        self.assertEqual(states[new["id"]], "current")


class TestLedger(Base):
    def test_ac07_ceiling_and_billers(self):
        with self.assertRaises(ledger.BudgetError):
            ledger.reserve(self.store, "openai", "api", "metered", 10)  # permit off
        ledger.set_permit(self.store, True)
        with self.assertRaises(ledger.BudgetError):
            ledger.reserve(self.store, "anthropic", "api", "metered", 1)
        with self.assertRaises(ledger.BudgetError):
            ledger.reserve(self.store, "openai", "api", "metered", None)
        ok, errs = [], []

        def worker():
            try:
                ok.append(ledger.reserve(self.store, "openai", "api", "metered", 10))
            except ledger.BudgetError:
                errs.append(1)

        th = [threading.Thread(target=worker) for _ in range(30)]
        [t.start() for t in th]
        [t.join() for t in th]
        self.assertEqual(len(ok), 16)
        self.assertLessEqual(ledger.totals(self.store)["committed"], 165)
        ledger.settle(self.store, ok[0], None)  # timeout -> ambiguous exposure retained
        self.assertEqual(ledger.totals(self.store)["ambiguous"], 10)
        with self.assertRaises(ledger.BudgetError):
            ledger.reserve(self.store, "openai", "api", "metered", 5.01)


class TestBoundaries(unittest.TestCase):
    def test_ac08_paths(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a").mkdir()
            self.assertTrue(
                str(contained_path(d, "a/x.txt")).startswith(str(Path(d).resolve()))
            )
            bad = ["../x", "a/../../x", "/etc/passwd"]
            if os.name == "nt":
                bad.extend(["..\\x", r"C:\Windows\x"])
            for rel in bad:
                with self.assertRaises(ScopeError):
                    contained_path(d, rel)
            link = Path(d) / "lnk"
            try:
                os.symlink(tempfile.gettempdir(), link, target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation not permitted")
            with self.assertRaises(ScopeError):
                contained_path(d, "lnk/x")

    def test_ac08_ssrf(self):
        for u in (
            "http://127.0.0.1/",
            "http://localhost:8765/",
            "http://169.254.169.254/latest",
            "http://10.0.0.1/",
            "file:///C:/Windows/win.ini",
            "http://user:pw@example.com/",
        ):
            with self.assertRaises(FetchError):
                safe_fetch(u)

    def test_ac09_redaction(self):
        s = redact(
            "key sk-proj-abcdefghijklmnopqrstu and ghp_abcdefghijklmnopqrstuvwxyz12 api_key=supersecretvalue"
        )
        self.assertNotIn("abcdefghijklmnop", s)
        self.assertNotIn("supersecretvalue", s)
        for secret, probe in (
            ("Authorization: Bearer abcdefghijklmnop1234", "abcdefghijklmnop1234"),
            ('{"password": "hunter2hunter2"}', "hunter2hunter2"),
            ("AIza" + "A" * 35, "A" * 35),
            (
                "-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJB\n-----END RSA PRIVATE KEY-----",
                "MIIBOgIBAAJB",
            ),
        ):
            self.assertNotIn(probe, redact(secret))

    def test_ac08_ssrf_cgnat(self):
        with self.assertRaises(FetchError):
            safe_fetch("http://100.64.0.1/")


class TestBackup(Base):
    def test_ac10_backup_restore_separate_dir(self):
        self.svc.attach(self.p["id"], "n.txt", b"synthetic")
        self.svc.save_artifact(self.p["id"], "note", "t", "c", None)
        arc = backup.create_backup(self.store, self.tmp / "bk")
        with self.assertRaises(ValueError):
            backup.restore_backup(arc, self.store.data_dir, self.store.data_dir)
        res = backup.restore_backup(arc, self.tmp / "restored", self.store.data_dir)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["counts"]["artifacts"], 1)
        self.assertIn("login", res["reauth"])


class TestHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="aesop-http-"))
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
        if "|KEY|" in h.get(
            "Cookie", ""
        ):  # test helper: cookie + origin key travel together
            h["Cookie"], h["X-Aesop-Key"] = h["Cookie"].split("|KEY|")
        c.request(
            method, path, body=json.dumps(body) if body is not None else None, headers=h
        )
        r = c.getresponse()
        data = r.read()
        return r.status, dict(r.getheaders()), data

    def login(self):
        code = self.srv.app.login_code
        if not code:
            return self.__class__._cookie, self.__class__._csrf
        st, hd, _ = self.req("GET", f"/login?code={code}")
        self.assertEqual(st, 303)
        cookie = (
            hd["Set-Cookie"].split(";")[0] + "|KEY|" + hd["Location"].split("#k=")[1]
        )
        self.assertIn("HttpOnly", hd["Set-Cookie"])
        _, _, d = self.req("GET", "/api/session", headers={"Cookie": cookie})
        self.__class__._cookie, self.__class__._csrf = cookie, json.loads(d)["csrf"]
        return cookie, self.__class__._csrf

    def test_ac08_listener_loopback_only(self):
        self.assertEqual(self.srv.server_address[0], "127.0.0.1")

    def test_session_reports_the_build_the_page_booted_with(self):
        cookie, _csrf = self.login()
        st, _, body = self.req("GET", "/api/session", headers={"Cookie": cookie})
        self.assertEqual(st, 200)
        data = json.loads(body)
        self.assertEqual(data["build"], int(self.srv.app.source_mtime * 1000))
        self.assertFalse(data["retiring"])

    def test_ac08_auth_origin_csrf_host(self):
        cookie, csrf = self.login()
        self.assertEqual(self.req("GET", "/api/projects")[0], 401)
        self.assertEqual(
            self.req(
                "GET", "/api/projects", headers={"Cookie": cookie, "Host": "evil.com"}
            )[0],
            421,
        )
        base = {"Cookie": cookie, "Content-Type": "application/json"}
        body = {"name": "x", "root": str(self.tmp)}
        self.assertEqual(
            self.req(
                "POST",
                "/api/projects",
                body,
                {**base, "Origin": "http://evil.com", "X-CSRF-Token": csrf},
            )[0],
            403,
        )
        self.assertEqual(
            self.req(
                "POST",
                "/api/projects",
                body,
                {**base, "Origin": f"http://127.0.0.1:{self.port}"},
            )[0],
            403,
        )
        st, hd, _ = self.req(
            "POST",
            "/api/projects",
            body,
            {**base, "Origin": f"http://127.0.0.1:{self.port}", "X-CSRF-Token": csrf},
        )
        self.assertEqual(st, 201)
        self.assertNotIn("Access-Control-Allow-Origin", hd)
        self.assertIn("default-src 'self'", hd["Content-Security-Policy"])
        self.assertEqual(self.req("GET", f"/login?code=reused")[0], 403)

    def test_frontend_parses(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        import subprocess

        r = subprocess.run(
            [
                node,
                "--check",
                str(Path(__file__).resolve().parent.parent / "static" / "app.js"),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_build_list_excludes_chat_tasks(self):
        cookie, csrf = self.login()
        app = self.srv.app
        root = self.tmp / "buildlist"
        root.mkdir(exist_ok=True)
        p = app.svc.create_project("B", str(root), "simulated")
        now = time.time()
        for tid, mode in (("task_chatx", "chat"), ("task_agentx", "agent")):
            app.store.x(
                "INSERT INTO tasks(id,project_id,provider,prompt,state,created,checkpoint) VALUES(?,?,?,?,?,?,?)",
                (
                    tid,
                    p["id"],
                    "simulated",
                    "x",
                    "COMPLETED",
                    now,
                    json.dumps({"mode": mode}),
                ),
            )
        st, _, body = self.req(
            "GET", f"/api/projects/{p['id']}/tasks", headers={"Cookie": cookie}
        )
        self.assertEqual(st, 200)
        self.assertEqual([t["id"] for t in json.loads(body)], ["task_agentx"])

    def test_chat_work_via_messages_http(self):
        cookie, csrf = self.login()
        origin = f"http://127.0.0.1:{self.port}"
        app = self.srv.app
        root = self.tmp / "workhttp"
        root.mkdir()
        p = app.svc.create_project("W", str(root), "simulated")
        app.store.x("INSERT INTO kv(k,v) VALUES(?, 'on')", (f"agent_ack:{p['id']}",))
        app.svc.update_project(p["id"], {"transfer_policy": {"simulated": True}})
        c = app.svc.new_conversation(p["id"])
        st, _, body = self.req(
            "POST",
            f"/api/projects/{p['id']}/conversations/{c['id']}/messages",
            {
                "text": "WRITE a file from chat",
                "attachment_ids": [],
                "provider": "simulated",
                "work": True,
            },
            {
                "Cookie": cookie,
                "Content-Type": "application/json",
                "Origin": origin,
                "X-CSRF-Token": csrf,
            },
        )
        self.assertEqual(st, 202)
        r = json.loads(body)
        self.assertTrue(r["work"])
        t = wait_state(app.sup, r["task_id"])
        self.assertEqual(t["state"], "COMPLETED")
        self.assertIn("sim_output.txt", json.loads(t["changed_files"])["added"])
        msgs = app.svc.messages(p["id"], c["id"])
        self.assertTrue(msgs[0]["meta"].get("work"))
        self.assertTrue(msgs[-1]["meta"].get("work"))

    def test_static_and_no_secrets_in_bundle(self):
        st, _, body = self.req("GET", "/app.js")
        self.assertEqual(st, 200)
        self.assertNotIn(b"innerHTML", body)
        self.assertIn(b'id: "workTog"', body)
        self.assertNotIn(b'data-tab="agent"', self.req("GET", "/")[2])
        self.assertEqual(self.req("GET", "/../aesop_studio/server.py")[0], 404)


if __name__ == "__main__":
    unittest.main()
