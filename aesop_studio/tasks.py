"""Supervised execution of official provider runtimes with a persisted state machine.

CREATED -> RESERVED -> STARTING -> RUNNING -> COMPLETED | FAILED | CANCELLED | INTERRUPTED
| BLOCKED_OWNER | EFFECT_UNKNOWN

Crash-safety rules used throughout:
- a ledger reservation is always settled *before* its task is marked terminal, so a crash leaves the task
  non-terminal and the next reconcile() settles it (settling is idempotent);
- reconcile() also sweeps reservations whose task is terminal or missing, so no reservation is orphaned;
- every worker thread ends in a terminal state, even on unexpected exceptions.
"""
from __future__ import annotations

import codecs
import hashlib
import json
import os
import shutil
import stat
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
READ_CHUNK = 64 * 1024
DEFAULT_TIMEOUT = 15 * 60
SNAPSHOT_LIMIT = 5000
SNAPSHOT_SECONDS = 20
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".aesop"}
NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
CHAT_DIR_PREFIX = "aesop-chat-"
OPEN_REPAIR_STATES = ("OPEN_FOREMAN", "EXPORTED_FOR_FOREMAN")
# Read-only chat turns on these plan-quota routes are retried once on a transient provider/network error.
SEPARATE_STDERR_ROUTES = {"zai", "claude"}


def _err_tail(out_path: str, n: int = 300) -> str:
    """Last diagnostic line(s) a CLI wrote to stderr (redacted, bounded)."""
    try:
        with open(out_path + ".err", "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 8192))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return redact(" | ".join(lines[-3:]))[-n:]


RETRY_ROUTES = {"zai", "grok", "cursor", "antigravity", "claude", "codex"}
TRANSIENT_MARKERS = ("429", "rate limit", "rate_limit", "overloaded", "503", "502", "504", "econnreset",
                     "etimedout", "socket hang up", "fetch failed", "network error", "temporarily unavailable",
                     "service unavailable", "bad gateway", "connection reset", "try again")
AGENT_ACK_STATEMENT = ("Agent tasks run the provider's official CLI as your Windows user. The project folder is its "
                       "working directory, not a sandbox: it can read files outside the folder that you can read. "
                       "Studio records the files it changed inside the folder.")


def _is_link(path: str) -> bool:
    """Symlinks and Windows junctions/reparse points are never followed."""
    try:
        if os.path.islink(path) or (hasattr(os.path, "isjunction") and os.path.isjunction(path)):
            return True
        st = os.lstat(path)
        return bool(getattr(st, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    except OSError:
        return True


def snapshot(root: str) -> tuple[dict[str, str], bool]:
    """Bounded, deterministic mtime+size fingerprint of a project root. Returns (entries, truncated)."""
    out: dict[str, str] = {}
    deadline = time.monotonic() + SNAPSHOT_SECONDS
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not _is_link(os.path.join(dirpath, d)))
        for f in sorted(filenames):
            p = os.path.join(dirpath, f)
            try:
                st = os.stat(p, follow_symlinks=False)
            except OSError:
                continue
            out[os.path.relpath(p, root)] = f"{st.st_mtime_ns}:{st.st_size}"
            if len(out) >= SNAPSHOT_LIMIT:
                return out, True
        if time.monotonic() > deadline:
            return out, True
    return out, False


def diff_snapshots(before: dict, after: dict, truncated: bool = False) -> dict:
    """When either snapshot was truncated, only files both sides saw are compared (no false adds/removes)."""
    if truncated:
        shared = set(before) & set(after)
        return {"added": [], "removed": [], "modified": sorted(k for k in shared if before[k] != after[k]),
                "incomplete": True}
    return {"added": sorted(set(after) - set(before)),
            "removed": sorted(set(before) - set(after)),
            "modified": sorted(k for k in set(before) & set(after) if before[k] != after[k])}


def kill_tree(pid: int) -> bool:
    """Terminate only the owned process tree by PID (never by image name)."""
    if os.name == "nt":
        try:
            r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=30,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    try:
        os.killpg(pid, 9)
        return True
    except OSError:
        return False


def pid_alive(pid: int) -> bool:
    if os.name == "nt":
        try:
            r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"], capture_output=True,
                               text=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired):
            return True  # cannot prove it is gone: treat as alive (conservative)
        return f'"{pid}"' in r.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _remove_chat_dir(cwd: str | None) -> None:
    """Delete a per-request chat sandbox — only ever a directory we created under the temp dir."""
    if not cwd:
        return
    p = Path(cwd).resolve()
    tmp = Path(tempfile.gettempdir()).resolve()
    if not p.name.startswith(CHAT_DIR_PREFIX):
        return
    try:
        p.relative_to(tmp)
    except ValueError:
        return
    for attempt in range(6):
        shutil.rmtree(p, ignore_errors=True)
        if not p.exists():
            return
        time.sleep(0.04 * (attempt + 1))


class _RedactingLog:
    """Streams text to the task log with redaction over whole spans and a hard byte cap.

    Text arrives in fragments (API deltas, pipe chunks), so a secret can be split across several of them. The
    buffer is redacted as a whole and only its settled prefix (up to whitespace at least HOLD characters before
    the end) is written; the tail stays buffered until more text arrives or the stream ends. A buffer that
    grows past MAX_BUF without a safe boundary is redacted and flushed anyway (bounded memory).
    """
    HOLD = 160
    MAX_BUF = 64 * 1024

    def __init__(self, path: str, max_bytes: int = MAX_OUTPUT_BYTES):
        self.f = open(path, "w", encoding="utf-8")
        self.buf = ""
        self.left = max_bytes
        self.truncated = False

    def _emit(self, text: str) -> None:
        if self.left <= 0:
            self.truncated = True
            return
        data = text.encode("utf-8")
        if len(data) > self.left:
            text = data[:self.left].decode("utf-8", errors="ignore")
            self.truncated = True
        self.f.write(text)
        self.f.flush()
        self.left -= len(text.encode("utf-8"))

    def write(self, delta: str) -> None:
        if self.left <= 0:
            self.truncated = True
            return
        self.buf += delta
        if len(self.buf) < 2 * self.HOLD:
            return
        red = redact(self.buf)
        limit = len(red) - self.HOLD
        cut = max(red.rfind(" ", 0, limit), red.rfind("\n", 0, limit))
        if cut <= 0:
            if len(self.buf) < self.MAX_BUF:
                return  # no safe boundary yet (e.g. one long token): keep buffering, bounded
            cut = limit
        self._emit(red[:cut])
        self.buf = red[cut:]

    def close(self) -> None:
        if self.buf:
            self._emit(redact(self.buf))
            self.buf = ""
        if self.truncated:
            self.f.write("\n[output truncated at limit]\n")
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

    def _end(self, tid: str, state: str, lid: str | None, billed, **fields) -> None:
        """Settle first, then go terminal: a crash between the two is repaired by reconcile()."""
        if lid:
            ledger.settle(self.store, lid, billed)
        self._set(tid, state, ended=time.time(), **fields)

    def final(self, task_id: str) -> dict | None:
        """The task that finally answers a request: follows an automatic transient-error retry (at most 2 hops)."""
        t = self.get(task_id)
        for _ in range(2):
            nxt = json.loads((t or {}).get("checkpoint") or "{}").get("retried_as") if t else None
            if not nxt:
                break
            t = self.get(nxt) or t
        return t

    def _maybe_retry(self, tid: str, route_id: str, mode: str, state: str, cp: dict, output_tail: str) -> str | None:
        if mode != "chat" or state != "FAILED" or route_id not in RETRY_ROUTES or cp.get("retry_of"):
            return None
        if tid in self.cancel_flags or tid + ":timeout" in self.cancel_flags:
            return None
        low = output_tail.lower()
        if not any(m in low for m in TRANSIENT_MARKERS):
            return None
        t = self.get(tid)
        proj = self.store.one("SELECT * FROM projects WHERE id=?", (t["project_id"],))
        if not proj:
            return None
        time.sleep(2)  # brief back-off before the single retry
        new = self.create(dict(proj), route_id, t["prompt"], mode="chat", timeout=cp.get("timeout") or DEFAULT_TIMEOUT)
        self.store.x("UPDATE tasks SET checkpoint=json_set(COALESCE(checkpoint,'{}'),'$.retry_of',?) WHERE id=?", (tid, new))
        self.store.event("task_retry", t["project_id"], task_id=tid, retry_task_id=new, route=route_id)
        return new

    def get(self, task_id: str) -> dict | None:
        return self.store.one("SELECT * FROM tasks WHERE id=?", (task_id,))

    def _busy(self, c, project_id: str):
        """One agent writer per project. An EFFECT_UNKNOWN agent task with an unresolved repair still blocks:
        its process may survive, so a second writer could collide with it until the owner resolves the repair."""
        return c.execute(
            "SELECT id FROM tasks WHERE project_id=? AND checkpoint LIKE '%\"mode\": \"agent\"%' AND ("
            "state IN ('CREATED','RESERVED','STARTING','RUNNING') OR (state='EFFECT_UNKNOWN' AND id IN ("
            f"SELECT task_id FROM repairs WHERE status IN ({','.join('?' * len(OPEN_REPAIR_STATES))}))))",
            (project_id, *OPEN_REPAIR_STATES)).fetchone()

    # ---- lifecycle ----
    def create(self, project: dict, route_id: str, prompt: str, mode: str = "agent",
               timeout: int = DEFAULT_TIMEOUT) -> str:
        routes = providers.cached(self.store)
        route = routes.get(route_id)
        tid = new_id("task")
        now = time.time()
        out_path = str(self.store.data_dir / "task-output" / f"{tid}.log")
        with self.store.tx() as c:  # busy check + insert are atomic
            busy = mode == "agent" and self._busy(c, project["id"])
            c.execute("INSERT INTO tasks(id,project_id,provider,prompt,state,cwd,output_path,created,checkpoint) "
                      "VALUES(?,?,?,?,?,?,?,?,?)",
                      (tid, project["id"], route_id, prompt, "CREATED", project["root"] if mode == "agent" else None,
                       out_path, now, json.dumps({"mode": mode, "timeout": timeout})))
        self.store.event("task_state", project["id"], task_id=tid, state="CREATED", mode=mode)
        if busy:
            self._end(tid, "BLOCKED_OWNER", None, None,
                      error=f"one agent writer per project: {busy[0]} is still active or awaiting repair review")
            return tid
        if not route or not providers.usable(route, mode):
            state = route["state"] if route else "UNKNOWN_ROUTE"
            self._end(tid, "BLOCKED_OWNER", None, None, error=f"route {route_id} not usable for {mode}: {state}")
            return tid
        if mode == "agent":
            ack = self.store.one("SELECT v FROM kv WHERE k=?", (f"agent_ack:{project['id']}",))
            if not (ack and ack["v"] == "on"):
                self._end(tid, "BLOCKED_OWNER", None, None,
                          error="acknowledge how agent tasks run before starting one: " + AGENT_ACK_STATEMENT)
                return tid
        if route["billing_basis"] == "metered":
            return self._start_api(tid, project, route_id, route, prompt, out_path, timeout)
        try:
            lid = ledger.reserve(self.store, route["provider"], route_id, route["billing_basis"], None, task_ref=tid)
        except ledger.BudgetError as e:
            self._end(tid, "BLOCKED_OWNER", None, None, error=str(e))
            return tid
        try:
            if mode == "agent":
                cwd = project["root"]
                before, truncated = snapshot(cwd)
                Path(out_path + ".before.json").write_text(json.dumps({"entries": before, "truncated": truncated}),
                                                           encoding="utf-8")
            else:  # created lazily: only requests that will really launch a CLI get a sandbox directory
                cwd, before, truncated = tempfile.mkdtemp(prefix=CHAT_DIR_PREFIX), {}, False
            cp = {"mode": mode, "timeout": timeout, "ledger_id": lid, "before_count": len(before),
                  "snapshot_truncated": truncated}
            self._set(tid, "RESERVED", checkpoint=json.dumps(cp), cwd=cwd)
        except Exception as e:  # noqa: BLE001 - nothing was dispatched: release the reservation
            self._end(tid, "FAILED", lid, 0, error=f"could not prepare the task: {type(e).__name__}: {str(e)[:200]}")
            return tid
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
            self._end(tid, "BLOCKED_OWNER", None, None, error=str(e))
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
        def release():
            with self.lock:
                self.api_cancel.pop(tid, None)

        try:  # pre-send: nothing can have been billed if anything here fails or the owner already cancelled
            if ev.is_set():
                release()
                return self._end(tid, "CANCELLED", lid, 0, error="cancelled before the request was sent")
            self._set(tid, "RUNNING", started=time.time(), argv_meta=json.dumps(
                {"endpoint": "POST /v1/responses", "model": model, "max_output_tokens": max_out}))
            key = openai_api.resolve_key()
            log = _RedactingLog(out_path)
        except Exception as e:  # noqa: BLE001
            release()
            msg = str(e) if isinstance(e, openai_api.ApiError) else f"could not start: {type(e).__name__}"
            return self._end(tid, "FAILED", lid, 0, error=redact(msg)[:500])
        try:
            try:
                r = openai_api.stream(prompt, model, max_out, log.write, ev, timeout, key=key)
            finally:
                key = None
                log.close()
        except openai_api.ApiError as e:
            release()
            msg = str(e)
            return self._end(tid, "FAILED", lid, 0 if msg.startswith("HTTP 4") else None, error=redact(msg)[:500])
        except Exception as e:  # noqa: BLE001 - never leave a task RUNNING with a live reservation
            release()
            return self._end(tid, "EFFECT_UNKNOWN", lid, None, error=f"unexpected stream error: {type(e).__name__}")
        release()
        try:
            cp = json.loads(self.get(tid)["checkpoint"] or "{}")
            cp["result"] = redact(r["text"])[:MAX_OUTPUT_BYTES]
            if r["status"] == "cancelled_presend":
                return self._end(tid, "CANCELLED", lid, 0, error="cancelled before the request was sent",
                                 checkpoint=json.dumps(cp))
            if r["status"] in ("cancelled", "deadline") or not r["usage"]:
                state = "CANCELLED" if r["status"] == "cancelled" else "EFFECT_UNKNOWN"
                note = ("timed out" if r["status"] == "deadline" else "stream stopped") + \
                       " before usage was reported; reservation kept as unresolved exposure"
                cp["cost_usd"] = None
                return self._end(tid, state, lid, None, error=note, checkpoint=json.dumps(cp))
            cost = openai_api.actual_cost(model, r["usage"])
            cp.update(usage=r["usage"], cost_usd=cost)
            err = None if r["status"] == "completed" else f"response {r['status']} (output cap {max_out} tokens)"
            self._end(tid, "COMPLETED", lid, cost, exit_code=0, error=err, checkpoint=json.dumps(cp))
        except Exception as e:  # noqa: BLE001 - bookkeeping failed after a billed call: keep exposure
            self._end(tid, "EFFECT_UNKNOWN", lid, None, error=f"bookkeeping failed: {type(e).__name__}")

    # ---- CLI routes ----
    def _run(self, tid, route_id, mode, cwd, prompt, out_path, timeout, lid, model):
        last_file = out_path + ".last.txt"
        proc = job = timer = None
        try:
            try:
                argv = providers.build_argv(route_id, mode, cwd, last_file, model, prompt=prompt)
            except RuntimeError as e:
                if mode != "agent":
                    _remove_chat_dir(cwd)
                return self._end(tid, "FAILED", lid, 0, error=str(e))
            meta = {"executable": Path(argv[0]).name,  # never record the prompt (argv-prompt routes) or the cwd
                    "args": ["-p=<prompt>" if a.startswith("-p=") else a for a in argv[1:] if not a.startswith(cwd)][:20]}
            self._set(tid, "STARTING", argv_meta=json.dumps(meta), started=time.time())
            env = {k: v for k, v in os.environ.items() if k.upper() not in providers.BILLING_ENV}
            try:
                # Claude Code-based routes write banners/diagnostics to stderr: keep them out of the answer.
                errf = open(out_path + ".err", "wb") if route_id in SEPARATE_STDERR_ROUTES else None
                proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=errf if errf else subprocess.STDOUT, creationflags=NEW_GROUP, env=env)
                if errf:
                    errf.close()  # the child holds its own handle
            except OSError as e:
                if mode != "agent":
                    _remove_chat_dir(cwd)
                return self._end(tid, "FAILED", lid, 0, error=f"launch failed: {e}")
            job = winjob.contain(proc.pid)  # whole-tree containment, including detached descendants
            with self.lock:
                self.procs[tid] = proc
                self.jobs[tid] = job
            # watchdog and output drain start BEFORE the prompt is written: a child that never reads stdin or that
            # fills stdout first can no longer deadlock the supervisor outside the timeout
            timer = threading.Timer(timeout, lambda: (self.cancel_flags.add(tid + ":timeout"),
                                                      winjob.terminate(job), kill_tree(proc.pid)))
            timer.daemon = True
            timer.start()
            log = _RedactingLog(out_path)

            def reader():
                dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
                try:
                    while True:
                        chunk = proc.stdout.read1(READ_CHUNK) if hasattr(proc.stdout, "read1") else \
                            proc.stdout.read(READ_CHUNK)
                        if not chunk:
                            break
                        if log.left > 0:
                            log.write(dec.decode(chunk))
                        # past the cap: keep draining so the child never blocks on a full pipe
                    log.write(dec.decode(b"", final=True))
                finally:
                    log.close()

            rt = threading.Thread(target=reader, daemon=True)
            rt.start()

            def writer():
                try:
                    if route_id not in providers.ARGV_PROMPT_ROUTES:
                        proc.stdin.write(prompt.encode("utf-8"))
                    proc.stdin.close()
                except (OSError, ValueError):
                    pass  # child exited or was killed; the pipe is gone

            wt = threading.Thread(target=writer, daemon=True)
            wt.start()
            self._set(tid, "RUNNING", pid=proc.pid)
            code = proc.wait()
            timer.cancel()
            wt.join(5)
            rt.join(10)
            descendants_killed, orphaned = False, False
            if rt.is_alive():  # a detached descendant still holds the output pipe: end the whole job
                descendants_killed = winjob.terminate(job)
                rt.join(5)
                orphaned = rt.is_alive()
            with self.lock:  # unregister and close atomically so cancel() never uses a recycled handle
                self.procs.pop(tid, None)
                self.jobs.pop(tid, None)
                winjob.close(job)
                job = None
            changed = None
            if mode == "agent":
                try:
                    saved = json.loads(Path(out_path + ".before.json").read_text(encoding="utf-8"))
                    after, trunc_after = snapshot(cwd)
                    changed = json.dumps(diff_snapshots(saved.get("entries", {}), after,
                                                        bool(saved.get("truncated")) or trunc_after))
                except (OSError, ValueError):
                    changed = json.dumps({"added": [], "removed": [], "modified": [], "incomplete": True,
                                          "note": "change snapshot unavailable"})
            result = ""
            try:
                with open(last_file, "rb") as f:  # bounded read, then the raw (unredacted) file is removed
                    result = redact(f.read(MAX_OUTPUT_BYTES).decode("utf-8", errors="replace"))
            except OSError:
                pass
            finally:
                try:
                    os.remove(last_file)
                except OSError:
                    pass
            if tid in self.cancel_flags:
                state, err = "CANCELLED", "cancelled by owner (local process tree terminated)"
            elif tid + ":timeout" in self.cancel_flags:
                state, err = "FAILED", f"timed out after {timeout}s"
            elif orphaned:
                state, err = "EFFECT_UNKNOWN", "main process exited but a descendant kept running; review before reuse"
            elif code == 0:
                state, err = "COMPLETED", ("left-over descendant processes were terminated via the task's job object"
                                           if descendants_killed else None)
            else:
                state, err = "FAILED", f"exit code {code}"
                diag = _err_tail(out_path)
                if diag:
                    err += f": {diag}"
            cp = json.loads(self.get(tid)["checkpoint"] or "{}")
            cp["result"] = result[:MAX_OUTPUT_BYTES]
            if state == "COMPLETED" and route_id in providers.LIVE_VERIFY_ROUTES:
                # every successful real call keeps the route's live verification fresh
                self.store.x("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                             (f"verify:{route_id}", json.dumps({"at": time.time(), "ok": True,
                                                                 "detail": "successful request", "latency_s": None})))
            try:
                tail = Path(out_path).read_text(encoding="utf-8", errors="replace")[-4000:] + " " + _err_tail(out_path, 2000)
            except OSError:
                tail = ""
            retry = self._maybe_retry(tid, route_id, mode, state, cp, tail + " " + (err or ""))
            if retry:  # recorded before going terminal, so readers following final() never see a dead end
                cp["retried_as"] = retry
                err = f"{err}; transient provider error, retried automatically as {retry}"
            if mode != "agent":
                _remove_chat_dir(cwd)
            self._end(tid, state, lid, 0, exit_code=code, changed_files=changed, error=err, checkpoint=json.dumps(cp))
            if state == "EFFECT_UNKNOWN":
                self.open_repair(tid, f"RUNNING->{state}", "task supervision / descendant cleanup")
        except BaseException as e:  # noqa: BLE001 - supervision must always reach a terminal state
            try:
                if timer:
                    timer.cancel()
                if proc is not None:
                    winjob.terminate(job)
                    kill_tree(proc.pid)
                with self.lock:
                    self.procs.pop(tid, None)
                    self.jobs.pop(tid, None)
                    if job:
                        winjob.close(job)
                t = self.get(tid)
                if t and t["state"] not in TERMINAL:
                    started = proc is not None
                    if mode != "agent":
                        _remove_chat_dir(cwd)
                    self._end(tid, "EFFECT_UNKNOWN" if started else "FAILED", lid, None if started else 0,
                              error=f"supervisor error: {type(e).__name__}: {str(e)[:200]}")
                    if started:
                        self.open_repair(tid, "RUNNING->EFFECT_UNKNOWN", "task supervision / supervisor exception")
            except Exception:  # noqa: BLE001 - last resort; reconcile() repairs anything left behind
                pass
        finally:
            if mode != "agent":
                _remove_chat_dir(cwd)

    def open_repair(self, tid: str, signature: str, contract: str) -> str:
        t = self.get(tid)
        rid = new_id("rep")
        self.store.x("INSERT INTO repairs(id,task_id,signature,reproducer,contract,status,created) VALUES(?,?,?,?,?,?,?)",
                     (rid, tid, signature,
                      f"task {tid} provider {t['provider']} prompt sha256 "
                      f"{hashlib.sha256(t['prompt'].encode()).hexdigest()[:16]}",
                      contract, "OPEN_FOREMAN", time.time()))
        return rid

    def resolve_repair(self, rid: str, note: str = "") -> dict:
        """Owner action: the uncertain effects were reviewed. Releases the project's agent-writer lock."""
        r = self.store.one("SELECT * FROM repairs WHERE id=?", (rid,))
        if not r:
            raise KeyError("repair not found")
        if r["status"] not in OPEN_REPAIR_STATES:
            raise ValueError("this repair is already resolved")
        self.store.x("UPDATE repairs SET status='RESOLVED_BY_OWNER' WHERE id=?", (rid,))
        self.store.event("repair_resolved", None, repair_id=rid, task_id=r["task_id"], note=note[:200])
        return self.store.one("SELECT * FROM repairs WHERE id=?", (rid,))

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
        if r["status"] == "OPEN_FOREMAN":
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
        """On restart: any non-terminal task from a previous process is never replayed; orphaned reservations
        (crash between reserve/link or settle/terminal) are settled conservatively."""
        outcomes = []
        for t in self.store.q("SELECT * FROM tasks WHERE state NOT IN (%s)" % ",".join("?" * len(TERMINAL)),
                              tuple(TERMINAL)):
            if t["state"] in ("CREATED", "RESERVED"):
                new_state, note = "INTERRUPTED", "no process was started; safe to resubmit manually"
            elif t["pid"] and pid_alive(t["pid"]):
                new_state, note = "EFFECT_UNKNOWN", "a process with the recorded PID is alive but ownership is unproven"
            else:
                new_state, note = "INTERRUPTED", "process ended while Studio was down; effects need review"
            cp = json.loads(t["checkpoint"] or "{}")
            metered_started = bool(cp.get("reservation_usd")) and t["state"] in ("STARTING", "RUNNING")
            billed = None if (metered_started or new_state == "EFFECT_UNKNOWN") else 0
            self._end(t["id"], new_state, cp.get("ledger_id"), billed, error=note)
            # Read-only chat turns have no side effects to review: only agent tasks get a repair packet.
            if t["state"] in ("STARTING", "RUNNING") and cp.get("mode") != "chat":  # unknown mode: conservative
                self.open_repair(t["id"], f"{t['state']}->{new_state}", "task supervision / restart reconciliation")
            if cp.get("mode") != "agent":
                _remove_chat_dir(t["cwd"])
            outcomes.append({"task_id": t["id"], "from": t["state"], "to": new_state, "note": note})
        # sweep: chat/verify sandboxes left by crashes or older builds (only our own prefixes, older than 24h)
        tmp = Path(tempfile.gettempdir())
        cutoff = time.time() - 24 * 3600
        for d in list(tmp.glob(CHAT_DIR_PREFIX + "*")) + list(tmp.glob("aesop-verify-*")):
            try:
                if d.is_dir() and not _is_link(str(d)) and d.stat().st_mtime < cutoff:
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                pass
        # sweep: reservations still open whose task is terminal or unknown (crash between the two writes)
        for row in self.store.q("SELECT l.id, l.billing_basis, l.task_ref, t.state, t.started FROM ledger l "
                                "LEFT JOIN tasks t ON t.id = l.task_ref WHERE l.status='reserved' AND "
                                "l.task_ref LIKE 'task_%'"):
            if row["state"] is not None and row["state"] not in TERMINAL:
                continue
            metered_maybe_sent = row["billing_basis"] == "metered" and row["started"]
            ledger.settle(self.store, row["id"], None if metered_maybe_sent else 0)
            outcomes.append({"ledger_id": row["id"], "to": "ambiguous" if metered_maybe_sent else "settled_0",
                             "note": "orphaned reservation reconciled"})
        return outcomes
