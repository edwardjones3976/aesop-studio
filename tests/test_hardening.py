"""Regression tests for verified hardening defects (security-03/04/08/09, stability-10/11/12/18/19)."""
import hashlib
import http.server
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

os.environ["AESOP_SIMULATED_ROUTE"] = "1"
os.environ["AESOP_PROBE_OFFLINE"] = "1"  # never launch real provider CLIs in tests

from aesop_studio import backup, services as services_mod  # noqa: E402
from aesop_studio.security import (FetchError, LineRedactor, ScopeError, redact, safe_fetch,  # noqa: E402
                                   sanitize_url, validate_root)
from aesop_studio.services import Conflict, Services  # noqa: E402
from aesop_studio.store import Store  # noqa: E402
from aesop_studio.tasks import Supervisor, TERMINAL  # noqa: E402

PEM = ("-----BEGIN RSA PRIVATE KEY-----\n"
       "MIIEowIBAAKCAQEAx1234567890abcdefghijklmnop\n"
       "QWERTYUIOPASDFGHJKLZXCVBNMqwertyuiopasdfgh\n"
       "-----END RSA PRIVATE KEY-----\n")
PEM_BODY = ("MIIEowIBAAKCAQEAx1234567890abcdefghijklmnop", "QWERTYUIOPASDFGHJKLZXCVBNMqwertyuiopasdfgh")


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
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-hard-"))
        self.root = self.tmp / "proj"
        self.root.mkdir()
        self.store = Store(self.tmp / "data")
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        from aesop_studio import providers
        providers.refresh(self.store)
        self.p = self.svc.create_project("Demo", str(self.root), "simulated")

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------- security-03: pinned fetch never goes through env proxies ----------

class _Tagged(http.server.BaseHTTPRequestHandler):
    tag = b""
    seen: list

    def do_GET(self):
        self.seen.append(dict(self.headers))
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(self.tag)))
        self.end_headers()
        self.wfile.write(self.tag)

    def log_message(self, *a):
        pass


def _serve(tag: bytes):
    seen = []
    handler = type("H", (_Tagged,), {"tag": tag, "seen": seen})
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, seen


class TestSafeFetchProxy(unittest.TestCase):
    def test_security03_env_proxy_not_used_for_pinned_fetch(self):
        direct, direct_seen = _serve(b"direct")
        proxy, proxy_seen = _serve(b"proxied")
        try:
            env = {"http_proxy": f"http://user:password@127.0.0.1:{proxy.server_port}",
                   "HTTP_PROXY": f"http://user:password@127.0.0.1:{proxy.server_port}"}
            with mock.patch.dict(os.environ, env):
                for k in ("no_proxy", "NO_PROXY"):
                    os.environ.pop(k, None)
                _, _, body = safe_fetch(f"http://127.0.0.1:{direct.server_port}/page", allow_hosts={"127.0.0.1"})
            self.assertEqual(body, "direct")
            self.assertEqual(proxy_seen, [])
            self.assertFalse(any("Proxy-Authorization" in h for h in direct_seen))
        finally:
            for s in (direct, proxy):
                s.shutdown()
                s.server_close()


# ---------- security-04: credential trees, their descendants and exposing ancestors ----------

class TestValidateRoot(unittest.TestCase):
    def test_security04_descendants_and_ancestors_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / "home"
            for sub in (".ssh", ".codex/provider-mcp-secrets", ".claude/projects", "Claude/Projects/foo"):
                (home / sub).mkdir(parents=True)
            with mock.patch.dict(os.environ, {"USERPROFILE": str(home), "HOME": str(home)}):
                self.assertEqual(Path.home(), home)
                for bad in (home, home / ".ssh", home / ".codex" / "provider-mcp-secrets",
                            home / ".claude" / "projects", home.parent):
                    with self.assertRaises(ScopeError, msg=str(bad)):
                        validate_root(str(bad))
                ok = home / "Claude" / "Projects" / "foo"
                self.assertEqual(validate_root(str(ok)), ok.resolve())
        sysroot = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
        if sysroot.is_dir():
            with self.assertRaises(ScopeError):
                validate_root(str(sysroot))


# ---------- security-08: multiline secrets ----------

class TestMultilineRedaction(unittest.TestCase):
    def test_security08_line_redactor_hides_pem_body(self):
        lr = LineRedactor()
        out = "".join(lr.feed(line) for line in ("before\n", *PEM.splitlines(keepends=True), "after\n"))
        for probe in PEM_BODY:
            self.assertNotIn(probe, out)
        self.assertIn("before", out)
        self.assertIn("after", out)
        # unterminated key: everything after BEGIN stays hidden
        lr = LineRedactor()
        out = "".join(lr.feed(line) for line in PEM.splitlines(keepends=True)[:3])
        for probe in PEM_BODY:
            self.assertNotIn(probe, out)

    def test_security08_redact_catches_orphaned_pem_body(self):
        per_line = "".join(redact(line) for line in PEM.splitlines(keepends=True))  # old line-by-line output
        for text in (per_line, json.dumps({"output": per_line})):
            red = redact(text)
            for probe in PEM_BODY:
                self.assertNotIn(probe, red)


# ---------- security-09: credential-bearing URLs ----------

class TestSourceUrls(Base):
    URL = "https://alice:hunter2pass@example.com/doc?token=abc123secretvalue&page=2"

    def _assert_clean(self, src):
        blob = json.dumps(src) + self.svc.export_notebook(self.p["id"])
        for secret in ("alice", "hunter2pass", "abc123secretvalue"):
            self.assertNotIn(secret, blob)

    def test_security09_failed_fetch_not_stored_verbatim(self):
        with mock.patch.object(services_mod, "safe_fetch", side_effect=FetchError("offline")) as f:
            src = self.svc.add_public_source(self.p["id"], self.URL)
        self.assertNotIn("alice", f.call_args[0][0])  # userinfo is never even sent
        self.assertEqual(src["publisher"], "example.com")
        self.assertIn("page=2", src["locator"])
        self._assert_clean(src)

    def test_security09_fetched_final_url_sanitized(self):
        final = "https://example.com/doc?access_token=abc123secretvalue&page=2"
        with mock.patch.object(services_mod, "safe_fetch", return_value=(final, "text/plain", "body")):
            src = self.svc.add_public_source(self.p["id"], self.URL)
        self.assertEqual(src["status"], "read")
        self._assert_clean(src)

    def test_security09_export_sanitizes_legacy_rows(self):
        self.store.x("INSERT INTO sources(id,project_id,kind,title,publisher,locator,status,private,created) "
                     "VALUES('src_old',?,'public',?,?,?,'unavailable',0,?)",
                     (self.p["id"], self.URL, "alice:hunter2pass@example.com", self.URL, time.time()))
        out = self.svc.export_notebook(self.p["id"])
        for secret in ("hunter2pass", "abc123secretvalue"):
            self.assertNotIn(secret, out)
        self.assertEqual(sanitize_url("https://example.com/a?b=c"), "https://example.com/a?b=c")


# ---------- stability-10 / stability-11: backups ----------

class TestBackupHardening(Base):
    def test_stability10_names_unique_and_never_overwritten(self):
        dest = self.tmp / "bk"
        arcs = []
        th = [threading.Thread(target=lambda: arcs.append(backup.create_backup(self.store, dest))) for _ in range(4)]
        [t.start() for t in th]
        [t.join() for t in th]
        self.assertEqual(len(set(arcs)), 4)
        for a in arcs:
            with zipfile.ZipFile(a) as z:
                self.assertIsNone(z.testzip())
        first = arcs[0]
        before = first.read_bytes()
        with mock.patch.object(backup, "_unique_name", return_value=first.name):
            with self.assertRaises(FileExistsError):
                backup.create_backup(self.store, dest)
        self.assertEqual(first.read_bytes(), before)
        self.assertEqual(list(dest.glob("*.partial")), [])

    def test_stability10_failed_backup_leaves_no_partial(self):
        dest = self.tmp / "bk"
        (self.store.data_dir / "task-output" / "task_x.log").write_text("log", encoding="utf-8")
        with mock.patch.object(backup, "redact", side_effect=RuntimeError("disk full")):
            with self.assertRaises(RuntimeError):
                backup.create_backup(self.store, dest)
        self.assertEqual(list(dest.iterdir()), [])

    def test_stability11_task_logs_backed_up_and_paths_remapped(self):
        c = self.svc.new_conversation(self.p["id"])
        r = self.svc.send(self.p["id"], c["id"], "hello", [], None)
        wait_state(self.sup, r["task_id"])
        blocked = self.sup.create(self.p, "no-such-route", "x", mode="chat")  # never runs, never logs
        self.assertEqual(self.sup.get(blocked)["state"], "BLOCKED_OWNER")
        log = Path(self.sup.get(r["task_id"])["output_path"])
        self.assertTrue(log.exists())
        arc = backup.create_backup(self.store, self.tmp / "bk")
        with zipfile.ZipFile(arc) as z:
            names = z.namelist()
            manifest = json.loads(z.read("manifest.json"))
        self.assertIn(f"task-output/{log.name}", names)
        self.assertFalse(any(n.endswith((".before.json", ".last.txt")) for n in names))
        self.assertIn("project root", manifest["external"])
        target = self.tmp / "restored"
        res = backup.restore_backup(arc, target, self.store.data_dir)
        self.assertTrue(res["ok"], res)
        self.assertIn(blocked, res["task_outputs_absent_at_backup"])
        con = sqlite3.connect(target / "aesop.db")
        path = con.execute("SELECT output_path FROM tasks WHERE id=?", (r["task_id"],)).fetchone()[0]
        con.close()
        self.assertTrue(Path(path).resolve().is_relative_to(target.resolve()), path)
        self.assertEqual(Path(path).read_bytes(), redact(log.read_text(encoding="utf-8")).encode("utf-8"))


# ---------- stability-12: atomic attachment writes ----------

class TestAttachmentAtomic(Base):
    def _stored(self, data, name):
        sha = hashlib.sha256(data).hexdigest()
        return self.store.data_dir / "files" / self.p["id"] / f"{sha[:16]}_{name}"

    def test_stability12_truncated_existing_file_rewritten(self):
        data = b"synthetic attachment " * 100
        p = self._stored(data, "n.txt")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data[:10])  # left behind by an interrupted write
        self.svc.attach(self.p["id"], "n.txt", data)
        self.assertEqual(p.read_bytes(), data)

    def test_stability12_failed_write_leaves_nothing(self):
        data = b"another synthetic file"
        p = self._stored(data, "m.txt")
        with mock.patch.object(services_mod.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.svc.attach(self.p["id"], "m.txt", data)
        self.assertFalse(p.exists())
        self.assertEqual(list(p.parent.glob("*.partial")), [])
        self.assertEqual(self.svc.attachments(self.p["id"]), [])
        self.svc.attach(self.p["id"], "m.txt", data)
        self.assertEqual(p.read_bytes(), data)


# ---------- stability-18: durable assistant-message link ----------

class TestChatDispatchLink(Base):
    def setUp(self):
        super().setUp()
        self.c = self.svc.new_conversation(self.p["id"])

    def _assistant(self):
        return [m for m in self.svc.messages(self.p["id"], self.c["id"]) if m["role"] == "assistant"]

    def test_stability18_placeholder_exists_before_dispatch(self):
        real = self.sup.create
        seen = []

        def spy(*a, **k):
            seen.append(self.store.q("SELECT status FROM messages WHERE conversation_id=? AND role='assistant'",
                                     (self.c["id"],)))
            return real(*a, **k)
        with mock.patch.object(self.sup, "create", side_effect=spy):
            r = self.svc.send(self.p["id"], self.c["id"], "hello", [], None)
        self.assertEqual(seen, [[{"status": "submitted"}]])
        wait_state(self.sup, r["task_id"])
        msgs = self._assistant()
        self.assertEqual(msgs[-1]["meta"]["task_id"], r["task_id"])
        self.assertEqual(msgs[-1]["status"], "generated")

    def test_stability18_lost_link_recovered(self):
        real = self.svc._link_task
        calls = []

        def flaky(mid, tid):
            calls.append(tid)
            if len(calls) == 1:
                raise OSError("disk I/O error")
            return real(mid, tid)
        with mock.patch.object(self.svc, "_link_task", side_effect=flaky):
            r = self.svc.send(self.p["id"], self.c["id"], "hello", [], None)
            wait_state(self.sup, r["task_id"])
            msgs = self._assistant()
        self.assertEqual(msgs[-1]["meta"]["task_id"], r["task_id"])
        self.assertEqual(msgs[-1]["status"], "generated")

    def test_stability18_dispatch_error_marks_placeholder_failed(self):
        with mock.patch.object(self.sup, "create", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.svc.send(self.p["id"], self.c["id"], "hello", [], None)
        self.assertEqual(self._assistant()[-1]["status"], "failed")

    def test_stability18_crash_before_dispatch_fails_after_grace(self):
        with mock.patch.object(self.sup, "create", side_effect=SystemExit("crash")):
            with self.assertRaises(SystemExit):
                self.svc.send(self.p["id"], self.c["id"], "hello", [], None)
        self.assertEqual(self._assistant()[-1]["status"], "submitted")  # still inside the grace window
        self.store.x("UPDATE messages SET created=created-? WHERE conversation_id=?",
                     (services_mod.DISPATCH_GRACE_S + 5, self.c["id"]))
        m = self._assistant()[-1]
        self.assertEqual(m["status"], "failed")
        self.assertIn("safe to resubmit", m["content"])


# ---------- stability-19: memory correction is one transaction ----------

class TestMemoryCorrection(Base):
    def _current_children(self, mid):
        return [m for m in self.svc.memory(self.p["id"]) if mid in m["source_ids"] and m["status"] == "current"]

    def test_stability19_repeat_correction_conflicts(self):
        m = self.svc.add_memory(self.p["id"], "authoritative", "note", "v1", [])
        self.svc.correct_memory(self.p["id"], m["id"], "v2")
        with self.assertRaises(Conflict):
            self.svc.correct_memory(self.p["id"], m["id"], "v3")
        self.assertEqual(len(self._current_children(m["id"])), 1)

    def test_stability19_concurrent_corrections_one_winner(self):
        m = self.svc.add_memory(self.p["id"], "authoritative", "note", "v1", [])
        ok, conflicts, barrier = [], [], threading.Barrier(8)

        def worker(i):
            barrier.wait()
            try:
                ok.append(self.svc.correct_memory(self.p["id"], m["id"], f"v{i}"))
            except Conflict:
                conflicts.append(i)
        th = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        [t.start() for t in th]
        [t.join() for t in th]
        self.assertEqual((len(ok), len(conflicts)), (1, 7))
        current = self._current_children(m["id"])
        self.assertEqual([x["id"] for x in current], [ok[0]["id"]])
        old = self.store.one("SELECT * FROM memory WHERE id=?", (m["id"],))
        self.assertEqual((old["status"], old["superseded_by"]), ("superseded", ok[0]["id"]))


if __name__ == "__main__":
    unittest.main()
