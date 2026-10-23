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

from . import ledger, providers
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


class Supervisor:
    def __init__(self, store: Store):
        self.store = store
        self.procs: dict[str, subprocess.Popen] = {}
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
        with self.lock:
            self.procs[tid] = proc
        self._set(tid, "RUNNING", pid=proc.pid)
        try:
            proc.stdin.write(prompt.encode("utf-8"))
            proc.stdin.close()
        except OSError:
            pass
        timer = threading.Timer(timeout, lambda: (self.cancel_flags.add(tid + ":timeout"), kill_tree(proc.pid)))
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
        if rt.is_alive():  # a detached descendant still holds the output pipe
            orphaned.set()
        with self.lock:
            self.procs.pop(tid, None)
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
            state, err = "COMPLETED", None
        else:
            state, err = "FAILED", f"exit code {code}"
        cp = json.loads(self.get(tid)["checkpoint"] or "{}")
        cp["result"] = result[:MAX_OUTPUT_BYTES]
        self._set(tid, state, exit_code=code, ended=time.time(), changed_files=changed, error=err,
                  checkpoint=json.dumps(cp))
        ledger.settle(self.store, lid, 0)

    def cancel(self, tid: str) -> bool:
        with self.lock:
            proc = self.procs.get(tid)
        if not proc:
            return False
        self.cancel_flags.add(tid)
        return kill_tree(proc.pid)

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
                ledger.settle(self.store, cp["ledger_id"], None if new_state == "EFFECT_UNKNOWN" else 0)
            if t["state"] in ("STARTING", "RUNNING"):
                rid = new_id("rep")
                self.store.x("INSERT INTO repairs(id,task_id,signature,reproducer,contract,status,created) "
                             "VALUES(?,?,?,?,?,?,?)",
                             (rid, t["id"], f"{t['state']}->{new_state}",
                              f"task {t['id']} prompt sha256 {hashlib.sha256(t['prompt'].encode()).hexdigest()[:16]}",
                              "task supervision / restart reconciliation", "OPEN_FOREMAN", time.time()))
            outcomes.append({"task_id": t["id"], "from": t["state"], "to": new_state, "note": note})
        return outcomes
