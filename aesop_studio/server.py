"""Loopback-only HTTP server with session cookie, Host/Origin checks and CSRF tokens."""
from __future__ import annotations

import argparse
import hmac
import json
import mimetypes
import os
import re
import secrets
import sys
import time
import urllib.parse
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import backup, evidence, ledger, providers
from .security import MAX_UPLOAD_BYTES, ScopeError, redact
from .services import Conflict, Services
from .store import Store
from .tasks import Supervisor

STATIC = Path(__file__).resolve().parent.parent / "static"
HOST = "127.0.0.1"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


class App:
    def __init__(self, data_dir: str, port: int):
        self.port = port
        self.store = Store(data_dir)
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        self.sessions: dict[str, str] = {}  # session -> csrf
        self.login_code = secrets.token_urlsafe(24)
        self.reconciled = self.sup.reconcile()
        providers.refresh(self.store)
        ledger.set_permit(self.store, False)  # shipped app never inherits a billable permit

    def allowed_hosts(self) -> set[str]:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}


ROUTES: list[tuple[str, re.Pattern, str]] = []


def route(method: str, pattern: str):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn.__name__))
        return fn
    return deco


class Handler(BaseHTTPRequestHandler):
    app: App
    server_version = "AesopStudio"
    sys_version = ""

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (time.strftime("%H:%M:%S"), redact(fmt % args).split("?")[0]))

    # ---------- plumbing ----------
    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, default=str).encode(), "application/json")

    def err(self, code: int, msg: str):
        self.json({"error": msg}, code)

    def _session(self) -> str | None:
        c = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        tok = c.get("aesop_session")
        return tok.value if tok and tok.value in self.app.sessions else None

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") in self.app.allowed_hosts()

    def body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n < 0 or n > 1_000_000:
            raise ValueError("request too large")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw or b"{}")

    # ---------- dispatch ----------
    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def _dispatch(self, method: str):
        if not self._host_ok():
            return self.err(421, "unexpected Host header")
        url = urllib.parse.urlsplit(self.path)
        self.query = urllib.parse.parse_qs(url.query)
        path = url.path
        if method == "GET" and path == "/login":
            return self._login()
        if method == "GET" and not path.startswith("/api/"):
            return self._static(path)
        sess = self._session()
        if not sess:
            return self.err(401, "not signed in to this Studio session; use the launch link printed at startup")
        if method != "GET":
            origin = self.headers.get("Origin")
            if origin not in {f"http://{h}" for h in self.app.allowed_hosts()}:
                return self.err(403, "cross-origin request rejected")
            if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), self.app.sessions[sess]):
                return self.err(403, "missing or invalid CSRF token")
        for m, pat, name in ROUTES:
            if m == method:
                mt = pat.match(path)
                if mt:
                    try:
                        return getattr(self, name)(sess, *mt.groups())
                    except KeyError as e:
                        return self.err(404, str(e).strip("'"))
                    except PermissionError as e:
                        return self.err(403, str(e))
                    except Conflict as e:
                        return self.err(409, str(e))
                    except (ValueError, ScopeError, ledger.BudgetError) as e:
                        return self.err(400, str(e))
        return self.err(404, "no such endpoint")

    def _login(self):
        code = (self.query.get("code") or [""])[0]
        if not self.app.login_code or not hmac.compare_digest(code, self.app.login_code):
            return self._send(403, b"Launch link expired. Restart Aesop Studio to get a new one.", "text/plain")
        self.app.login_code = ""  # one-time
        sess = secrets.token_urlsafe(32)
        self.app.sessions[sess] = secrets.token_urlsafe(32)
        self._send(303, b"", "text/plain", {
            "Location": "/", "Set-Cookie": f"aesop_session={sess}; HttpOnly; SameSite=Strict; Path=/"})

    def _static(self, path: str):
        if path == "/":
            path = "/index.html"
        f = (STATIC / path.lstrip("/")).resolve()
        if STATIC not in f.parents or not f.is_file():
            return self.err(404, "not found")
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(200, f.read_bytes(), ctype)

    # ---------- API ----------
    @route("GET", r"/api/session")
    def session(self, sess):
        self.json({"csrf": self.app.sessions[sess], "reconciled": self.app.reconciled, "port": self.app.port})

    @route("GET", r"/api/routes")
    def routes(self, sess):
        self.json(providers.cached(self.app.store))

    @route("POST", r"/api/routes/refresh")
    def routes_refresh(self, sess):
        self.json(providers.refresh(self.app.store))

    @route("GET", r"/api/projects")
    def projects(self, sess):
        self.json(self.app.svc.projects())

    @route("POST", r"/api/projects")
    def project_create(self, sess):
        b = self.body()
        self.json(self.app.svc.create_project(b.get("name", ""), b.get("root", ""), b.get("provider_default")), 201)

    @route("GET", r"/api/projects/(\w+)")
    def project_get(self, sess, pid):
        self.json(self.app.svc.project(pid))

    @route("PATCH", r"/api/projects/(\w+)")
    def project_patch(self, sess, pid):
        self.json(self.app.svc.update_project(pid, self.body()))

    @route("POST", r"/api/projects/(\w+)/archive")
    def project_archive(self, sess, pid):
        self.app.svc.archive_project(pid)
        self.json({"archived": pid, "note": "Project hidden. Files in the project root and stored attachments "
                                            "were not deleted."})

    @route("GET", r"/api/projects/(\w+)/attachments")
    def attachments(self, sess, pid):
        self.json(self.app.svc.attachments(pid))

    @route("POST", r"/api/projects/(\w+)/attachments")
    def attach(self, sess, pid):
        n = int(self.headers.get("Content-Length") or 0)
        if n < 0:
            raise ValueError("invalid Content-Length")
        name = urllib.parse.unquote(self.headers.get("X-Filename", "file"))
        if n > MAX_UPLOAD_BYTES:
            self.rfile.read(min(n, MAX_UPLOAD_BYTES + 1))  # drain bounded
            self.app.svc.project(pid)
            return self.json({"name": name, "extract_status": "too_large",
                              "extract_note": "File exceeds the 5 MB limit and was not stored."}, 413)
        self.json(self.app.svc.attach(pid, name, self.rfile.read(n)), 201)

    @route("GET", r"/api/projects/(\w+)/conversations")
    def convs(self, sess, pid):
        self.json(self.app.svc.conversations(pid))

    @route("POST", r"/api/projects/(\w+)/conversations")
    def conv_new(self, sess, pid):
        self.json(self.app.svc.new_conversation(pid, self.body().get("title", "")), 201)

    @route("GET", r"/api/projects/(\w+)/conversations/(\w+)/messages")
    def msgs(self, sess, pid, cid):
        self.json(self.app.svc.messages(pid, cid))

    @route("POST", r"/api/projects/(\w+)/conversations/(\w+)/preview")
    def preview(self, sess, pid, cid):
        b = self.body()
        p = self.app.svc.project(pid)
        prov = b.get("provider") or p["provider_default"]
        ctx = self.app.svc.build_context(pid, cid, b.get("text", ""), b.get("attachment_ids", []), prov)
        self.json({"provider": prov, "context": ctx, "chars": len(ctx)})

    @route("POST", r"/api/projects/(\w+)/conversations/(\w+)/messages")
    def send(self, sess, pid, cid):
        b = self.body()
        self.json(self.app.svc.send(pid, cid, b.get("text", ""), b.get("attachment_ids", []), b.get("provider"),
                                    bool(b.get("confirm_switch"))), 202)

    @route("GET", r"/api/projects/(\w+)/artifacts")
    def artifacts(self, sess, pid):
        self.json(self.app.svc.artifacts(pid))

    @route("POST", r"/api/projects/(\w+)/artifacts")
    def artifact_new(self, sess, pid):
        b = self.body()
        self.json(self.app.svc.save_artifact(pid, b.get("kind", "note"), b.get("title", ""), b.get("content", ""),
                                             b.get("source_ref")), 201)

    @route("GET", r"/api/projects/(\w+)/export")
    def export(self, sess, pid):
        svc = self.app.svc
        p = svc.project(pid)
        data = {"project": p, "artifacts": svc.artifacts(pid), "attachments": svc.attachments(pid),
                "conversations": [{"conversation": c, "messages": svc.messages(pid, c["id"])}
                                  for c in svc.conversations(pid)],
                "notebook": svc.notebook(pid), "memory": svc.memory(pid), "exported_at": time.time()}
        body = redact(json.dumps(data, default=str, indent=1)).encode()
        self._send(200, body, "application/json", {
            "Content-Disposition": f'attachment; filename="aesop-{pid}.json"'})

    @route("GET", r"/api/projects/(\w+)/tasks")
    def tasks(self, sess, pid):
        self.app.svc.project(pid)
        self.json(self.app.store.q("SELECT id,provider,state,prompt,error,exit_code,created,started,ended,"
                                   "changed_files,checkpoint FROM tasks WHERE project_id=? ORDER BY created DESC "
                                   "LIMIT 50", (pid,)))

    @route("POST", r"/api/projects/(\w+)/tasks")
    def task_new(self, sess, pid):
        b = self.body()
        p = self.app.svc.project(pid)
        prov = b.get("provider") or p["provider_default"]
        if p["provider_default"] and prov != p["provider_default"] and not b.get("confirm_switch"):
            raise Conflict(f"this project uses {p['provider_default']}; confirm switching to {prov} explicitly")
        if not (b.get("prompt") or "").strip():
            raise ValueError("task prompt is empty")
        tid = self.app.sup.create(p, prov, b["prompt"].strip(), mode="agent",
                                  timeout=max(30, min(3600, int(b.get("timeout", 900)))))
        self.json(self.app.sup.get(tid), 202)

    def _task(self, tid):
        t = self.app.sup.get(tid)
        if not t:
            raise KeyError("task not found")
        return t

    @route("GET", r"/api/tasks/(\w+)")
    def task_get(self, sess, tid):
        t = self._task(tid)
        off = int((self.query.get("offset") or ["0"])[0])
        out, new_off = self.app.sup.output(tid, off)
        self.json({"task": t, "output": out, "offset": new_off})

    @route("POST", r"/api/tasks/(\w+)/cancel")
    def task_cancel(self, sess, tid):
        self._task(tid)
        ok = self.app.sup.cancel(tid)
        self.json({"cancel_signalled": ok, "note": "Local process tree terminated; remote work stop is not provable."})

    @route("POST", r"/api/tasks/(\w+)/save")
    def task_save(self, sess, tid):
        t = self._task(tid)
        cp = json.loads(t["checkpoint"] or "{}")
        content = cp.get("result") or self.app.sup.output(tid)[0]
        content += "\n\nChanged files: " + (t["changed_files"] or "n/a")
        self.json(self.app.svc.save_artifact(t["project_id"], "task_result", f"Task {tid} ({t['state']})",
                                             content, tid), 201)

    @route("GET", r"/api/projects/(\w+)/notebook")
    def notebook(self, sess, pid):
        self.json(self.app.svc.notebook(pid))

    @route("POST", r"/api/projects/(\w+)/notebook/sources")
    def source_new(self, sess, pid):
        b = self.body()
        if b.get("attachment_id"):
            return self.json(self.app.svc.add_local_source(pid, b["attachment_id"]), 201)
        self.json(self.app.svc.add_public_source(pid, b.get("url", "")), 201)

    @route("POST", r"/api/projects/(\w+)/notebook/findings")
    def finding_new(self, sess, pid):
        b = self.body()
        self.json(self.app.svc.add_finding(pid, b.get("claim", ""), b.get("source_id"), b.get("locator", ""),
                                           b.get("limitation", "")), 201)

    @route("GET", r"/api/projects/(\w+)/notebook/export")
    def notebook_export(self, sess, pid):
        md = self.app.svc.export_notebook(pid, (self.query.get("private") or ["0"])[0] == "1")
        self._send(200, md.encode(), "text/markdown; charset=utf-8",
                   {"Content-Disposition": f'attachment; filename="notebook-{pid}.md"'})

    @route("GET", r"/api/projects/(\w+)/search")
    def search(self, sess, pid):
        self.json(self.app.svc.search(pid, (self.query.get("q") or [""])[0][:200]))

    @route("GET", r"/api/projects/(\w+)/memory")
    def memory(self, sess, pid):
        self.json(self.app.svc.memory(pid))

    @route("POST", r"/api/projects/(\w+)/memory")
    def memory_new(self, sess, pid):
        b = self.body()
        self.json(self.app.svc.add_memory(pid, b.get("layer", "authoritative"), b.get("kind", "note"),
                                          b.get("content", ""), b.get("source_ids", [])), 201)

    @route("POST", r"/api/projects/(\w+)/memory/(\w+)/(correct|mark|promote)")
    def memory_op(self, sess, pid, mid, op):
        b = self.body()
        if op == "correct":
            return self.json(self.app.svc.correct_memory(pid, mid, b.get("content", "")))
        if op == "mark":
            self.app.svc.mark_memory(pid, mid, b.get("status", ""))
            return self.json({"ok": True})
        self.json(self.app.svc.promote_memory(pid, mid))

    @route("GET", r"/api/projects/(\w+)/context-packet")
    def packet(self, sess, pid):
        self.json(self.app.svc.context_packet(pid))

    @route("POST", r"/api/repairs/(\w+)/export")
    def repair_export(self, sess, rid):
        self.json({"packet": str(self.app.sup.export_repair(rid)),
                   "note": "Packet written locally for the Foreman; Studio does not dispatch repairs itself."})

    @route("GET", r"/api/evidence")
    def evidence_get(self, sess):
        self.json(evidence.collect(self.app.store))

    @route("POST", r"/api/workflow-measure")
    def workflow_measure(self, sess):
        b = self.body()
        rec = {k: b.get(k) for k in ("label", "workflow", "elapsed_s", "manual_steps", "app_switches",
                                     "provider", "persisted", "notes")}
        self.app.store.event("workflow_measure", None, **rec)
        self.json(rec, 201)

    @route("POST", r"/api/backup")
    def do_backup(self, sess):
        out = backup.create_backup(self.app.store, self.app.store.data_dir / "backups")
        self.json({"archive": str(out)}, 201)

    @route("POST", r"/api/backup/verify")
    def backup_verify(self, sess):
        backups = sorted((self.app.store.data_dir / "backups").glob("aesop-backup-*.zip"))
        if not backups:
            raise ValueError("no backup exists yet")
        target = self.app.store.data_dir / "restore-tests" / time.strftime("%Y%m%d-%H%M%S")
        res = backup.restore_backup(backups[-1], target, self.app.store.data_dir)
        self.app.store.event("restore_test", None, ok=res["ok"], archive=backups[-1].name)
        self.json(res)


def make_server(data_dir: str, port: int) -> ThreadingHTTPServer:
    app = App(data_dir, port)
    handler = type("BoundHandler", (Handler,), {"app": app})
    srv = ThreadingHTTPServer((HOST, port), handler)
    srv.daemon_threads = True
    srv.app = app
    return srv


def main(argv=None):
    ap = argparse.ArgumentParser(description="Aesop Studio (loopback only)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("AESOP_PORT", 8765)))
    ap.add_argument("--data", default=os.environ.get("AESOP_DATA",
                                                     str(Path(os.environ.get("LOCALAPPDATA", ".")) / "AesopStudio")))
    a = ap.parse_args(argv)
    srv = make_server(a.data, a.port)
    url = f"http://127.0.0.1:{a.port}/login?code={srv.app.login_code}"
    link_file = Path(a.data) / "launch-link.txt"
    link_file.write_text(url, encoding="utf-8")
    print(f"Aesop Studio listening on http://127.0.0.1:{a.port} (loopback only)")
    print(f"One-time launch link written to {link_file}")
    if srv.app.reconciled:
        print(f"Reconciled {len(srv.app.reconciled)} unfinished task(s) from the previous run.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        link_file.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
