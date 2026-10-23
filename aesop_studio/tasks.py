"""Supervised execution of official provider runtimes with a persisted state machine.

CREATED -> RESERVED -> STARTING -> RUNNING -> COMPLETED | FAILED | CANCELLED | INTERRUPTED
| BLOCKED_OWNER | EFFECT_UNKNOWN
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from . import ledger, openai_api, providers, winjob
from .security import redact
from .store import Store, new_id

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED", "BLOCKED_OWNER", "EFFECT_UNKNOWN"}
MAX_OUTPUT_BYTES = 512 * 1024
DEFAULT_TIMEOUT = 15 * 60
SNAPSHOT_LIMIT = 5000
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".aesop"}
NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)


def snapshot(root: str) -> dict[str, str]:
    """Bounded mtime+size fingerprint of a project root (no symlink/junction following)."""
    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d))]
        for f in filenames:
            p = os.path.join(dirpath, f)
            try:
                st = os.stat(p, follow_symlinks=False)
            except OSError:
                continue
            out[os.path.relpath(p, root)] = f"{st.st_mtime_ns}:{st.st_size}"
            if len(out) >= SNAPSHOT_LIMIT:
                return out
    return out


def diff_snapshots(before: dict, after: dict) -> dict:
    return {"added": sorted(set(after) - set(before)),
            "removed": sorted(set(before) - set(after)),
            "modified": sorted(k for k in set(before) & set(after) if before[k] != after[k])}


def kill_tree(pid: int) -> bool:
    """Terminate only the owned process tree by PID (never by image name)."""
    if os.name == "nt":
        r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0
    try:
        os.killpg(pid, 9)
        return True
    except OSError:
        return False


def pid_alive(pid: int) -> bool:
    if os.name == "nt":
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"], capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return f'"{pid}"' in r.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class _RedactingLog:
    """Streams API deltas to the task log with redaction over whole spans.

    Deltas are a few tokens long, so a secret can arrive split across several of them. The buffer is
    redacted as a whole and only its settled prefix (up to whitespace at least HOLD characters before
    the end) is written; the tail stays buffered until more text arrives or the stream ends.
    """
    HOLD = 160

    def __init__(self, path: str):
        self.f = open(path, "w", encoding="utf-8")
        self.buf = ""

    def write(self, delta: str) -> None:
        self.buf += delta
        if len(self.buf) < 2 * self.HOLD:
            return
        red = redact(self.buf)
        limit = len(red) - self.HOLD
        cut = max(red.rfind(" ", 0, limit), red.rfind("\n", 0, limit))
        if cut <= 0:
            return  # no safe boundary yet (e.g. one long token): keep buffering
        self.f.write(red[:cut])
        self.f.flush()
        self.buf = red[cut:]

    def close(self) -> None:
        if self.buf:
            self.f.write(redact(self.buf))
            self.buf = ""
        self.f.close()


class Supervisor:
    def __init__(self, store: Store):
        self.store = store
        self.procs: dict[str, subprocess.Popen] = {}
        self.jobs: dict[str, object] = {}
        self.api_cancel: dict[str, threading.Event] = {}
        self.cancel_flags: set[str] = set()
        self.lock = threading.Lock()

    # ---- state ----
    def _set(self, task_id: str, state: str, **fields) -> None:
        cols = ", ".join(f"{k}=?" for k in fields)
        sql = f"UPDATE tasks SET state=?{', ' + cols if cols else ''} WHERE id=?"
        self.store.x(sql, (state, *fields.values(), task_id))
        t = self.store.one("SELECT project_id FROM tasks WHERE id=?", (task_id,))
        self.store.event("task_state", t and t["project_id"], task_id=task_id, state=state)

    def get(self, task_id: str) -> dict | None:
        return self.store.one("SELECT * FROM tasks WHERE id=?", (task_id,))

    # ---- lifecycle ----
    def create(self, project: dict, route_id: str, prompt: str, mode: str = "agent",
               timeout: int = DEFAULT_TIMEOUT) -> str:
        routes = providers.cached(self.store)
        route = routes.get(route_id)
        tid = new_id("task")
        now = time.time()
        cwd = project["root"] if mode == "agent" else tempfile.mkdtemp(prefix="aesop-chat-")
        out_path = str(self.store.data_dir / "task-output" / f"{tid}.log")
        with self.store.tx() as c:  # busy check + insert are atomic: one agent writer per project
            busy = mode == "agent" and c.execute(
                "SELECT id FROM tasks WHERE project_id=? AND checkpoint LIKE '%\"mode\": \"agent\"%' AND state IN "
                "('CREATED','RESERVED','STARTING','RUNNING')", (project["id"],)).fetchone()
            c.execute("INSERT INTO tasks(id,project_id,provider,prompt,state,cwd,output_path,created,checkpoint) "
                      "VALUES(?,?,?,?,?,?,?,?,?)",
                      (tid, project["id"], route_id, prompt, "CREATED", cwd, out_path, now,
                       json.dumps({"mode": mode, "timeout": timeout})))
        self.store.event("task_state", project["id"], task_id=tid, state="CREATED", mode=mode)
        if busy:
            self._set(tid, "BLOCKED_OWNER", error=f"one agent writer per project: {busy[0]} is still active",
                      ended=time.time())
            return tid
        if not route or not providers.usable(route, mode):
            state = route["state"] if route else "UNKNOWN_ROUTE"
            self._set(tid, "BLOCKED_OWNER", error=f"route {route_id} not usable for {mode}: {state}", ended=time.time())
            return tid
        if route["billing_basis"] == "metered":
            return self._start_api(tid, project, route_id, route, prompt, out_path, timeout)
        try:
            lid = ledger.reserve(self.store, route["provider"], route_id, route["billing_basis"], None, task_ref=tid)
        except ledger.BudgetError as e:
            self._set(tid, "BLOCKED_OWNER", error=str(e), ended=time.time())
            return tid
        before = snapshot(cwd) if mode == "agent" else {}
        cp = {"mode": mode, "timeout": timeout, "ledger_id": lid, "before_count": len(before)}
        Path(out_path + ".before.json").write_text(json.dumps(before), encoding="utf-8")
        self._set(tid, "RESERVED", checkpoint=json.dumps(cp))
        threading.Thread(target=self._run, args=(tid, route_id, mode, cwd, prompt, out_path, timeout, lid,
                                                 project.get("model")), daemon=True).start()
        return tid

    # ---- metered API route (no subprocess; streamed, reserved, settled from real usage) ----
    def _start_api(self, tid, project, route_id, route, prompt, out_path, timeout) -> str:
        model = project.get("model") if project.get("model") in openai_api.PRICES else openai_api.DEFAULT_MODEL
        max_out = openai_api.DEFAULT_MAX_OUTPUT
        try:
            cap = openai_api.max_cost(model, len(prompt.encode("utf-8")), max_out)
            lid = ledger.reserve(self.store, route["provider"], route_id, "metered", cap, task_ref=tid,
                                 price_source=f"{model}: {openai_api.PRICE_SOURCE}")
        except (ledger.BudgetError, openai_api.ApiError) as e:
            self._set(tid, "BLOCKED_OWNER", error=str(e), ended=time.time())
            return tid
        cp = {"mode": "chat", "timeout": timeout, "ledger_id": lid, "model": model, "max_output_tokens": max_out,
              "reservation_usd": cap}
        self._set(tid, "RESERVED", checkpoint=json.dumps(cp), reservation_usd=cap)
        ev = threading.Event()
        with self.lock:
            self.api_cancel[tid] = ev
        threading.Thread(target=self._run_api, args=(tid, prompt, out_path, timeout, lid, model, max_out, ev),
                         daemon=True).start()
        return tid

    def _run_api(self, tid, prompt, out_path, timeout, lid, model, max_out, ev):
        self._set(tid, "RUNNING", started=time.time(),
                  argv_meta=json.dumps({"endpoint": "POST /v1/responses", "model": model, "max_output_tokens": max_out}))

        def finish_failed(msg: str, billed):
            ledger.settle(self.store, lid, billed)
            self._set(tid, "FAILED", error=redact(msg)[:500], ended=time.time())
            with self.lock:
                self.api_cancel.pop(tid, None)

        try:  # pre-send: nothing can have been billed if this fails
            key = openai_api.resolve_key()
        except Exception as e:  # noqa: BLE001 - any failure here is pre-dispatch
            return finish_failed(str(e) if isinstance(e, openai_api.ApiError) else "OpenAI key could not be resolved", 0)
        log = _RedactingLog(out_path)
        try:
            r = openai_api.stream(prompt, model, max_out, log.write, ev, timeout, key=key)
        except openai_api.ApiError as e:
            log.close()
            msg = str(e)
            return finish_failed(msg, 0 if msg.startswith("HTTP 4") else None)  # unknown outcome keeps exposure
        except Exception as e:  # noqa: BLE001 - never leave a task RUNNING with a live reservation
            log.close()
            return finish_failed(f"unexpected stream error: {type(e).__name__}", None)
        finally:
            key = None
        log.close()
        with self.lock:
            self.api_cancel.pop(tid, None)
        cp = json.loads(self.get(tid)["checkpoint"] or "{}")
        cp["result"] = redact(r["text"])[:MAX_OUTPUT_BYTES]
        if r["status"] == "cancelled" or not r["usage"]:
            ledger.settle(self.store, lid, None)  # tokens may have been generated: keep reserved exposure
            state = "CANCELLED" if r["status"] == "cancelled" else "EFFECT_UNKNOWN"
            err, cost = "stream stopped before usage was reported; reservation kept as unresolved exposure", None
        else:
            cost = openai_api.actual_cost(model, r["usage"])
            ledger.settle(self.store, lid, cost)
            cp["usage"] = r["usage"]
            state = "COMPLETED"
            err = None if r["status"] == "completed" else f"response {r['status']} (output cap {max_out} tokens)"
        cp["cost_usd"] = cost
        self._set(tid, state, exit_code=0 if state == "COMPLETED" else None, ended=time.time(), error=err,
                  checkpoint=json.dumps(cp))

    def _run(self, tid, route_id, mode, cwd, prompt, out_path, timeout, lid, model):
        last_file = out_path + ".last.txt"
        try:
            argv = providers.build_argv(route_id, mode, cwd, last_file, model)
        except RuntimeError as e:
            self._set(tid, "FAILED", error=str(e), ended=time.time())
            ledger.settle(self.store, lid, 0)
            return
        meta = {"executable": Path(argv[0]).name, "args": [a for a in argv[1:] if not a.startswith(cwd)][:20]}
        self._set(tid, "STARTING", argv_meta=json.dumps(meta), started=time.time())
        env = {k: v for k, v in os.environ.items() if k.upper() not in providers.BILLING_ENV}
        try:
            proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, creationflags=NEW_GROUP, env=env)
        except OSError as e:
            self._set(tid, "FAILED", error=f"launch failed: {e}", ended=time.time())
            ledger.settle(self.store, lid, 0)
            return
        job = winjob.contain(proc.pid)  # whole-tree containment, including detached descendants
        with self.lock:
            self.procs[tid] = proc
            self.jobs[tid] = job
        self._set(tid, "RUNNING", pid=proc.pid)
        try:
            proc.stdin.write(prompt.encode("utf-8"))
            proc.stdin.close()
        except OSError:
            pass
        timer = threading.Timer(timeout, lambda: (self.cancel_flags.add(tid + ":timeout"), winjob.terminate(job),
                                                  kill_tree(proc.pid)))
        timer.start()
        orphaned = threading.Event()

        def reader():
            written = 0
            with open(out_path, "w", encoding="utf-8") as log:
                for raw in iter(proc.stdout.readline, b""):
                    line = redact(raw.decode("utf-8", errors="replace"))
                    if written < MAX_OUTPUT_BYTES:
                        log.write(line)
                        log.flush()
                        written += len(line)
                if written >= MAX_OUTPUT_BYTES:
                    log.write("\n[output truncated at limit]\n")
        rt = threading.Thread(target=reader, daemon=True)
        rt.start()
        code = proc.wait()
        timer.cancel()
        rt.join(10)
        descendants_killed = False
        if rt.is_alive():  # a detached descendant still holds the output pipe: end the whole job
            descendants_killed = winjob.terminate(job)
            rt.join(5)
            if rt.is_alive():
                orphaned.set()
        with self.lock:  # unregister and close atomically so cancel() never uses a recycled handle
            self.procs.pop(tid, None)
            self.jobs.pop(tid, None)
            winjob.close(job)
        changed = None
        if mode == "agent":
            try:
                before = json.loads(Path(out_path + ".before.json").read_text(encoding="utf-8"))
                changed = json.dumps(diff_snapshots(before, snapshot(cwd)))
            except OSError:
                changed = None
        result = ""
        if os.path.exists(last_file):
            result = redact(Path(last_file).read_text(encoding="utf-8", errors="replace"))
        if tid in self.cancel_flags:
            state, err = "CANCELLED", "cancelled by owner (local process tree terminated)"
        elif tid + ":timeout" in self.cancel_flags:
            state, err = "FAILED", f"timed out after {timeout}s"
        elif orphaned.is_set():
            state, err = "EFFECT_UNKNOWN", "main process exited but a descendant kept running; review before reuse"
        elif code == 0:
            state, err = "COMPLETED", ("left-over descendant processes were terminated via the task's job object"
                                       if descendants_killed else None)
        else:
            state, err = "FAILED", f"exit code {code}"
        cp = json.loads(self.get(tid)["checkpoint"] or "{}")
        cp["result"] = result[:MAX_OUTPUT_BYTES]
        self._set(tid, state, exit_code=code, ended=time.time(), changed_files=changed, error=err,
                  checkpoint=json.dumps(cp))
        ledger.settle(self.store, lid, 0)
        if state == "EFFECT_UNKNOWN":
            self.open_repair(tid, f"RUNNING->{state}", "task supervision / descendant cleanup")

    def open_repair(self, tid: str, signature: str, contract: str) -> str:
        t = self.get(tid)
        rid = new_id("rep")
        self.store.x("INSERT INTO repairs(id,task_id,signature,reproducer,contract,status,created) VALUES(?,?,?,?,?,?,?)",
                     (rid, tid, signature,
                      f"task {tid} provider {t['provider']} prompt sha256 "
                      f"{hashlib.sha256(t['prompt'].encode()).hexdigest()[:16]}",
                      contract, "OPEN_FOREMAN", time.time()))
        return rid

    def export_repair(self, rid: str) -> Path:
        """Write a formal, sanitized repair packet for the Foreman. Studio never dispatches it itself."""
        r = self.store.one("SELECT * FROM repairs WHERE id=?", (rid,))
        if not r:
            raise KeyError("repair not found")
        t = self.get(r["task_id"]) or {}
        packet = {
            "format": "aesop-repair-packet/1", "repair_id": rid, "status": "READY_FOR_FOREMAN",
            "failure_signature": r["signature"], "reproducer": r["reproducer"],
            "affected_contract": r["contract"], "task": {k: t.get(k) for k in (
                "id", "provider", "state", "exit_code", "error", "cwd", "created", "started", "ended")},
            "changed_files": json.loads(t.get("changed_files") or "null"),
            "allowed_paths": ["aesop_studio/tasks.py", "aesop_studio/winjob.py", "tests/test_studio.py"],
            "required_tests": ["python -W ignore -m unittest tests.test_studio"],
            "scope": "Fix the supervision fault only; no provider, billing or permission changes.",
            "budget_usd": 0, "rollback": "git revert of the repair commit; task records are append-only",
            "owner": "Foreman (Director-Orchestrator), via the owner's existing authorized workflow",
            "replay_policy": "Never replay the original task automatically; the owner resubmits after review.",
            "exported_at": time.time()}
        out_dir = self.store.data_dir / "foreman-outbox"
        out_dir.mkdir(exist_ok=True)
        out = out_dir / f"{rid}.json"
        out.write_text(redact(json.dumps(packet, indent=2, default=str)), encoding="utf-8")
        self.store.x("UPDATE repairs SET status='EXPORTED_FOR_FOREMAN' WHERE id=?", (rid,))
        return out

    def cancel(self, tid: str) -> bool:
        with self.lock:
            proc = self.procs.get(tid)
            api_ev = self.api_cancel.get(tid)
        if api_ev:
            api_ev.set()
            return True
        if not proc:
            return False
        self.cancel_flags.add(tid)
        with self.lock:
            by_job = winjob.terminate(self.jobs.get(tid))
        return kill_tree(proc.pid) or by_job

    def output(self, tid: str, offset: int = 0) -> tuple[str, int]:
        t = self.get(tid)
        if not t or not t["output_path"] or not os.path.exists(t["output_path"]):
            return "", offset
        with open(t["output_path"], "r", encoding="utf-8", errors="replace") as f:
            f.seek(offset)
            data = f.read(64 * 1024)
            return data, f.tell()

    def reconcile(self) -> list[dict]:
        """On restart: any non-terminal task from a previous process is never replayed."""
        outcomes = []
        for t in self.store.q("SELECT * FROM tasks WHERE state NOT IN (%s)" % ",".join("?" * len(TERMINAL)),
                              tuple(TERMINAL)):
            if t["state"] in ("CREATED", "RESERVED"):
                new_state, note = "INTERRUPTED", "no process was started; safe to resubmit manually"
            elif t["pid"] and pid_alive(t["pid"]):
                new_state, note = "EFFECT_UNKNOWN", "a process with the recorded PID is alive but ownership is unproven"
            else:
                new_state, note = "INTERRUPTED", "process ended while Studio was down; effects need review"
            self._set(t["id"], new_state, error=note, ended=time.time())
            cp = json.loads(t["checkpoint"] or "{}")
            if cp.get("ledger_id"):
                metered_started = cp.get("reservation_usd") and t["state"] in ("STARTING", "RUNNING")
                ledger.settle(self.store, cp["ledger_id"],
                              None if new_state == "EFFECT_UNKNOWN" or metered_started else 0)
            if t["state"] in ("STARTING", "RUNNING"):
                self.open_repair(t["id"], f"{t['state']}->{new_state}", "task supervision / restart reconciliation")
            outcomes.append({"task_id": t["id"], "from": t["state"], "to": new_state, "note": note})
        return outcomes
