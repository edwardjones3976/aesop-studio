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
import threading
import time
import urllib.parse
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import backup, deletion, derive, evidence, followup, lanes, team, ledger, providers, researcher, roundtable, roundtable_compare
from .security import MAX_UPLOAD_BYTES, ScopeError, redact
from .services import Conflict, Services
from .sessions import SESSION_DAYS, Sessions
from .store import Store
from . import tasks as tasks_mod
from .tasks import Supervisor

STATIC = Path(__file__).resolve().parent.parent / "static"
HOST = "127.0.0.1"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; "
       "frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


class InstanceLockError(RuntimeError):
    pass


def _lock_data_dir(data_dir: str):
    """Exclusive, process-lifetime lock on the data directory: a second server must never reconcile (and so
    mislabel) the first server's live tasks. The OS releases the lock when the process exits."""
    d = Path(data_dir)
    d.mkdir(parents=True, exist_ok=True)
    fh = open(d / "server.lock", "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        fh.close()
        raise InstanceLockError(f"another Aesop Studio instance owns the data directory {d}") from e
    return fh


class App:
    def __init__(self, data_dir: str, port: int):
        self.port = port
        self._instance_lock = _lock_data_dir(data_dir)
        self.store = Store(data_dir)
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        self.sessions = Sessions(self.store.data_dir)  # persistent: survives restarts (30-day sliding)
        self.login_code = secrets.token_urlsafe(24)
        self.reconciled = self.sup.reconcile()
        from .roundtable_live import Broker
        self.broker = Broker(self.store, self.sup)
        self.reconciled += self.broker.reconcile()
        team.resume(self.store, self.sup, self.svc)
        providers.refresh(self.store)
        # The mission permit is the owner's switch (Evidence -> Spend controls). It survives restarts (owner request
        # 2026-10-23: "switch all API routes to on"); a fresh install starts off, and the $165 mission ceiling
        # still bounds every reservation.

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
        self._sitem = self.app.sessions.get(tok.value if tok else None)
        return tok.value if self._sitem else None

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
        if not self.app.sessions.key_ok(self._sitem, self.headers.get("X-Aesop-Key", "")):
            return self.err(401, "missing or invalid Studio key; reopen Studio from its launch link")
        if method != "GET":
            origin = self.headers.get("Origin")
            if origin not in {f"http://{h}" for h in self.app.allowed_hosts()}:
                return self.err(403, "cross-origin request rejected")
            if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), self._sitem["csrf"]):
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
        sess, _csrf, key = self.app.sessions.create()
        self._send(303, b"", "text/plain", {
            "Location": f"/#k={key}",
            "Set-Cookie": f"aesop_session={sess}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_DAYS * 86400}"})

    def _static(self, path: str):
        if path == "/favicon.ico":  # the page declares its own icon; answer quietly instead of 404 noise
            return self._send(204, b"", "image/x-icon")
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
        self.json({"csrf": self._sitem["csrf"], "reconciled": self.app.reconciled, "port": self.app.port})

    @route("GET", r"/api/routes")
    def routes(self, sess):
        self.json(providers.cached(self.app.store))

    @route("POST", r"/api/routes/refresh")
    def routes_refresh(self, sess):
        self.json(providers.refresh(self.app.store))

    @route("POST", r"/api/routes/([\w-]+)/verify")
    def route_verify(self, sess, rid):
        """Owner-triggered: one minimal read-only call to a single CLI route proves sign-in and remaining quota."""
        rec = providers.verify_live(self.app.store, rid)
        self.json({"verification": rec, "routes": providers.refresh(self.app.store)})

    # ---------- roundtables: drafts, compare, and live broker (gated by owner "Live roundtables" switch) ----------
    @route("GET", r"/api/roundtable/lanes")
    def rt_lanes(self, sess):
        self.json(lanes.discover(self.app.store))

    @route("GET", r"/api/projects/(\w+)/roundtables")
    def rt_list(self, sess, pid):
        self.app.svc.project(pid)
        self.json(roundtable.list_for(self.app.store, pid))

    @route("POST", r"/api/projects/(\w+)/roundtables")
    def rt_save(self, sess, pid):
        self.app.svc.project(pid)
        self.json(roundtable.save(self.app.store, pid, self.body()), 201)

    def _rt(self, rid):
        rec = roundtable.get(self.app.store, rid)
        if not rec:
            raise KeyError("roundtable not found")
        return rec

    @route("GET", r"/api/roundtables/(\w+)")
    def rt_get(self, sess, rid):
        self.json(self._rt(rid))

    @route("POST", r"/api/roundtables/(\w+)/preflight")
    def rt_preflight(self, sess, rid):
        self.json(roundtable.preflight(self.app.store, self._rt(rid)))

    @route("POST", r"/api/roundtables/(\w+)/compare")
    def rt_compare(self, sess, rid):
        rec = self._rt(rid)
        b = self.body()
        out = roundtable_compare.start(self.app.store, self.app.sup, self.app.svc, rec,
                                       confirm=bool(b.get("confirm")))
        code = 202 if out.get("status") == "RUNNING" else (409 if out.get("status") == "BLOCKED" else 200)
        self.json(out, code)

    @route("GET", r"/api/roundtable/live-authorization")
    def rt_live_auth_get(self, sess):
        self.json({"live_authorized": lanes.live_authorized(self.app.store)})

    @route("POST", r"/api/roundtable/live-authorization")
    def rt_live_auth(self, sess):
        lanes.set_live_authorized(self.app.store, bool(self.body().get("enabled")))
        self.json({"live_authorized": lanes.live_authorized(self.app.store)})

    @route("POST", r"/api/roundtables/(\w+)/start")
    def rt_start(self, sess, rid):
        rec = self._rt(rid)
        res = self.app.broker.start(rec, self.app.svc.project(rec["project_id"]))
        if not res["started"]:
            return self.json({"error": "Preflight did not pass.", "block_reasons": res["block_reasons"]}, 409)
        self.json(res, 202)

    @route("POST", r"/api/roundtables/(\w+)/(pause|resume|stop)")
    def rt_control(self, sess, rid, op):
        self._rt(rid)
        self.json(getattr(self.app.broker, op)(rid))

    @route("POST", r"/api/roundtables/(\w+)/research")
    def rt_research(self, sess, rid):
        self._rt(rid)
        self.json(self.app.broker.ask_research(rid, self.body().get("query") or ""), 202)

    @route("GET", r"/api/roundtables/(\w+)/followup")
    def rt_followup(self, sess, rid):
        rec = self._rt(rid)
        refresh = (self.query.get("refresh") or ["0"])[0] == "1"
        self.json(followup.prepare(self.app.store, self.app.sup, self.app.broker, rec,
                                   self.app.svc.project(rec["project_id"]), refresh=refresh))

    @route("POST", r"/api/roundtables/(\w+)/followup")
    def rt_followup_save(self, sess, rid):
        rec = self._rt(rid)
        self.json(followup.complete(self.app.store, self.app.broker, rec, self.app.svc.project(rec["project_id"]),
                                    self.body()))

    @route("GET", r"/api/roundtable/researcher")
    def rt_researcher(self, sess):
        self.json({**researcher.status(), "used_today": researcher.daily_used(self.app.store)})

    @route("GET", r"/api/roundtables")
    def rt_history(self, sess):
        """History of every roundtable across projects (newest first)."""
        rows = self.app.store.q("SELECT r.id, r.project_id, p.name AS project, r.mode, r.objective, r.live_status, "
                                "r.started, r.ended, r.coverage, r.updated, (SELECT COUNT(*) FROM roundtable_events e "
                                "WHERE e.rt_id = r.id AND e.kind IN ('opening','message','closing')) AS messages "
                                "FROM roundtables r JOIN projects p ON p.id = r.project_id ORDER BY r.updated DESC LIMIT 200")
        for r in rows:
            r["coverage"] = json.loads(r["coverage"]) if r["coverage"] else None
        self.json(rows)

    @route("POST", r"/api/projects/(\w+)/conversations/(\w+)/delete")
    def conv_delete(self, sess, pid, cid):
        self.json(deletion.delete_conversation(self.app.store, self.app.svc, pid, cid))

    @route("POST", r"/api/roundtables/(\w+)/delete")
    def rt_delete(self, sess, rid):
        rec = self._rt(rid)
        live = self.app.broker.sessions.get(rid)
        if (rec.get("live_status") in ("RUNNING", "PAUSED")) or (live and live["thread"].is_alive()):
            raise Conflict("stop this session before deleting it")
        self.json(deletion.delete_roundtable(self.app.store, rid))

    @route("GET", r"/api/roundtables/(\w+)/live")
    def rt_live(self, sess, rid):
        self._rt(rid)
        after = int((self.query.get("after") or ["0"])[0])
        self.json({"status": self.app.broker.status(rid), "events": self.app.broker.events(rid, after)})

    @route("GET", r"/api/roundtables/(\w+)/record")
    def rt_record(self, sess, rid):
        self._rt(rid)
        body = redact(json.dumps(self.app.broker.export(rid), indent=1, default=str)).encode()
        self._send(200, body, "application/json", {"Content-Disposition": f'attachment; filename="roundtable-record-{rid}.json"'})

    @route("GET", r"/api/roundtables/(\w+)/export")
    def rt_export(self, sess, rid):
        rec = self._rt(rid)
        packet = roundtable.export_packet(self.app.store, rec, self.app.svc.project(rec["project_id"]))
        self._send(200, redact(json.dumps(packet, indent=1, default=str)).encode(), "application/json",
                   {"Content-Disposition": f'attachment; filename="roundtable-{rid}.json"'})

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

    @route("POST", r"/api/attachments/(\w+)/discard")
    def attachment_discard(self, sess, aid):
        self.json(self.app.svc.discard_unsent(aid))

    @route("GET", r"/api/attachments/(\w+)/image")
    def attachment_image(self, sess, aid):
        try:
            path, mime = self.app.svc.image_file(aid)
        except KeyError:  # not a photo (a text file, or already removed): nothing to show, not an error
            return self._send(204, b"", "text/plain")
        self._send(200, path.read_bytes(), mime, {"Cache-Control": "private, max-age=86400"})

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
                                   "changed_files,checkpoint FROM tasks WHERE project_id=? AND checkpoint LIKE '%\"mode\": \"agent\"%' "
                                   "ORDER BY created DESC LIMIT 50", (pid,)))

    @route("POST", r"/api/projects/(\w+)/tasks")
    def task_new(self, sess, pid):
        b = self.body()
        p = self.app.svc.project(pid)
        prov = b.get("provider") or p["provider_default"]
        # an explicit provider in the request is the owner's choice; no extra confirmation
        if not (b.get("prompt") or "").strip():
            raise ValueError("task prompt is empty")
        reviewer = b.get("reviewer") or None
        if reviewer and reviewer not in team.reviewers(self.app.store, prov):
            raise ValueError(f"{reviewer} can't review right now; pick another reviewer or none")
        tid = self.app.sup.create(p, prov, b["prompt"].strip(), mode="agent",
                                  timeout=max(30, min(3600, int(b.get("timeout", 900)))))
        # every build gets its tests run by Studio afterwards; a reviewer (optional) then sees the results
        team.plan(self.app.store, tid, reviewer)
        team.watch(self.app.store, self.app.sup, self.app.svc, tid)
        self.json(self.app.sup.get(tid), 202)

    @route("GET", r"/api/projects/(\w+)/reviewers")
    def task_reviewers(self, sess, pid):
        p = self.app.svc.project(pid)
        self.json({"builder": p["provider_default"], "reviewers": team.reviewers(self.app.store, p["provider_default"]),
                   "max_rounds": team.MAX_ROUNDS})

    @route("GET", r"/api/tasks/(\w+)/review")
    def task_review(self, sess, tid):
        self._task(tid)
        self.json(team.get(self.app.store, tid) or {"state": "NONE"})

    @route("POST", r"/api/tasks/(\w+)/review")
    def task_review_again(self, sess, tid):
        self._task(tid)
        self.json(team.retry(self.app.store, self.app.sup, self.app.svc, tid, self.body().get("reviewer")), 202)

    @route("POST", r"/api/tasks/(\w+)/tests")
    def task_tests(self, sess, tid):
        t = self._task(tid)
        if t["state"] != "COMPLETED":
            raise ValueError("tests run on completed builds only")
        threading.Thread(target=team.run_tests, args=(self.app.store, self.app.sup, self.app.svc, tid), daemon=True).start()
        self.json({"started": True}, 202)

    @route("POST", r"/api/tasks/(\w+)/fixes")
    def task_fixes(self, sess, tid):
        self._task(tid)
        b = self.body()
        picked = b.get("issues")
        self.json(team.send_fixes(self.app.store, self.app.sup, self.app.svc, tid,
                                  [int(x) for x in picked] if isinstance(picked, list) else None, b.get("note") or ""), 202)

    @route("POST", r"/api/tasks/(\w+)/accept")
    def task_accept(self, sess, tid):
        self._task(tid)
        self.json(team.accept(self.app.store, tid))

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
        cp = json.loads(t["checkpoint"] or "{}")
        # Metered API tasks stream answer text; CLI task logs echo prompts and banners and are not the answer.
        self.json({"task": t, "output": out, "offset": new_off,
                   "stream_is_answer": bool(cp.get("model") and "reservation_usd" in cp)})

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

    # ---------- model-assisted proposals (one provider: the project's route; owner accepts or rejects) ----------
    @route("POST", r"/api/projects/(\w+)/notebook/draft-findings")
    def draft_findings(self, sess, pid):
        b = self.body()
        self.json(derive.draft_findings(self.app.store, self.app.svc, self.app.sup, pid, b.get("source_ids") or [],
                                        b.get("provider"), bool(b.get("confirm_switch"))), 202)

    @route("POST", r"/api/projects/(\w+)/conversations/(\w+)/summarize")
    def summarize(self, sess, pid, cid):
        b = self.body()
        self.json(derive.summarize_conversation(self.app.store, self.app.svc, self.app.sup, pid, cid,
                                                b.get("provider"), bool(b.get("confirm_switch"))), 202)

    @route("GET", r"/api/derivations/(\w+)")
    def derivation(self, sess, did):
        self.json(derive.get(self.app.store, self.app.svc, self.app.sup, did))

    @route("POST", r"/api/projects/(\w+)/notebook/findings/(\w+)/(accept|reject)")
    def finding_decide(self, sess, pid, fid, op):
        self.json(derive.decide_finding(self.app.store, pid, fid, op == "accept"))

    @route("POST", r"/api/projects/(\w+)/memory/(\w+)/(accept|reject)")
    def memory_decide(self, sess, pid, mid, op):
        self.json(derive.decide_memory(self.app.store, pid, mid, op == "accept"))

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

    @route("POST", r"/api/repairs/(\w+)/resolve")
    def repair_resolve(self, sess, rid):
        """Owner: uncertain effects were reviewed; releases the project's agent-writer lock held by that task."""
        self.json(self.app.sup.resolve_repair(rid, str(self.body().get("note", ""))))

    @route("POST", r"/api/projects/(\w+)/agent-ack")
    def agent_ack(self, sess, pid):
        """Owner acknowledgement required before agent tasks run in this project (see filesystem_scope)."""
        self.app.svc.project(pid)
        on = bool(self.body().get("ack"))
        self.app.store.x("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                         (f"agent_ack:{pid}", "on" if on else "off"))
        self.app.store.event("agent_ack", pid, ack=on)
        self.json({"project_id": pid, "agent_ack": on})

    @route("GET", r"/api/projects/(\w+)/agent-ack")
    def agent_ack_get(self, sess, pid):
        self.app.svc.project(pid)
        row = self.app.store.one("SELECT v FROM kv WHERE k=?", (f"agent_ack:{pid}",))
        self.json({"project_id": pid, "agent_ack": bool(row and row["v"] == "on"),
                   "statement": tasks_mod.AGENT_ACK_STATEMENT})

    @route("POST", r"/api/repairs/(\w+)/export")
    def repair_export(self, sess, rid):
        self.json({"packet": str(self.app.sup.export_repair(rid)),
                   "note": "Packet written locally for the Foreman; Studio does not dispatch repairs itself."})

    @route("GET", r"/api/evidence")
    def evidence_get(self, sess):
        self.json(evidence.collect(self.app.store))

    @route("POST", r"/api/budget")
    def budget_set(self, sess):
        """Owner spend controls. The mission permit is forced off again at every server start."""
        b = self.body()
        if "runtime_limit_usd" in b:
            ledger.set_runtime_limit(self.app.store, float(b["runtime_limit_usd"] or 0))
        if "mission_permit" in b:
            ledger.set_permit(self.app.store, bool(b["mission_permit"]))
        self.app.store.event("budget_change", None, **{k: b[k] for k in ("runtime_limit_usd", "mission_permit")
                                                        if k in b})
        self.json({"budget": ledger.totals(self.app.store), "routes": providers.cached(self.app.store)})

    @route("POST", r"/api/ledger/(\w+)/resolve")
    def ledger_resolve(self, sess, lid):
        b = self.body()
        ledger.resolve(self.app.store, lid, float(b.get("actual_usd", "nan")), str(b.get("note", "")))
        self.json({"budget": ledger.totals(self.app.store)})

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
    try:
        srv = make_server(a.data, a.port)
    except InstanceLockError as e:
        print(f"Aesop Studio not started: {e}", file=sys.stderr)
        raise SystemExit(2)
    url = f"http://127.0.0.1:{a.port}/login?code={srv.app.login_code}"
    link_file = Path(a.data) / "launch-link.txt"
    link_file.write_text(url, encoding="utf-8")
    print(f"Aesop Studio listening on http://127.0.0.1:{a.port} (loopback only)")
    print(f"One-time launch link written to {link_file}")

    def relogin_watch():
        req = Path(a.data) / "relogin.request"
        while True:
            time.sleep(0.5)
            if req.exists():
                try:
                    req.unlink()
                except OSError:
                    continue
                srv.app.login_code = secrets.token_urlsafe(24)  # previous unused code is invalidated
                link_file.write_text(f"http://127.0.0.1:{a.port}/login?code={srv.app.login_code}", encoding="utf-8")

    def reverify_watch():
        while True:
            for rid in providers.due_reverify(srv.app.store):
                try:
                    providers.verify_live(srv.app.store, rid)
                    providers.refresh(srv.app.store)
                except Exception as e:  # never let a provider hiccup stop the watcher
                    print(f"background verification of {rid} failed: {type(e).__name__}")
            time.sleep(600)

    import threading as _threading
    _threading.Thread(target=relogin_watch, daemon=True).start()
    _threading.Thread(target=reverify_watch, daemon=True).start()
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
