"""Studio-side manager for the headless Chromium worker (aesop_studio.browser_worker).

The Studio server runs under an interpreter without Playwright, so the browser lives in a subprocess started with
the project's .venv Python. One worker per Studio instance, launched on first use, restarted if it dies. Every
command is one request/one reply, serialized by a lock with a timeout, so a slow page never blocks another caller.
"""
from __future__ import annotations

import base64
import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKER = Path(__file__).with_name("browser_worker.py")
LAUNCH_TIMEOUT = 60
CMD_TIMEOUT = 45
NEW_GROUP = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def venv_python() -> Path | None:
    for c in (REPO / ".venv" / "Scripts" / "python.exe", REPO / ".venv" / "bin" / "python",
              REPO / "venv" / "Scripts" / "python.exe"):
        if c.is_file():
            return c
    return None


class Browser:
    def __init__(self):
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.q: queue.Queue = queue.Queue()
        self.last = {"url": "", "title": ""}
        self.started_at = 0.0
        self.error = ""

    # ---- availability ----
    def available(self) -> bool:
        return venv_python() is not None and WORKER.is_file()

    def status(self) -> dict:
        return {"available": self.available(),
                "running": bool(self.proc and self.proc.poll() is None),
                "url": self.last.get("url", ""), "title": self.last.get("title", ""),
                "error": self.error,
                "note": "" if self.available() else
                        "The browser needs Playwright + Chrome in the project's .venv. Run: "
                        ".venv\\Scripts\\python -m playwright install chrome"}

    # ---- lifecycle ----
    def _reader(self, proc):
        for line in proc.stdout:
            line = line.strip()
            if line:
                self.q.put(line)
        self.q.put(None)  # EOF

    def _ensure(self) -> None:
        if self.proc and self.proc.poll() is None:
            return
        py = venv_python()
        if not py:
            raise RuntimeError("browser unavailable: no project .venv Python with Playwright")
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break
        self.proc = subprocess.Popen([str(py), "-I", str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, cwd=str(REPO), text=True, encoding="utf-8",
                                     bufsize=1, creationflags=NEW_GROUP)
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()
        try:
            ready = self.q.get(timeout=LAUNCH_TIMEOUT)
        except queue.Empty:
            self._kill()
            raise RuntimeError("browser did not start within the time limit")
        if ready is None or not json.loads(ready).get("ready"):
            self._kill()
            raise RuntimeError("browser worker failed to initialize")
        self.started_at = time.time()
        self.error = ""

    def _kill(self) -> None:
        if self.proc:
            try:
                self.proc.kill()
            except OSError:
                pass
        self.proc = None

    def cmd(self, op: str, timeout: int = CMD_TIMEOUT, **args) -> dict:
        with self.lock:
            self._ensure()
            try:
                self.proc.stdin.write(json.dumps({"op": op, **args}) + "\n")
                self.proc.stdin.flush()
            except (OSError, ValueError):
                self._kill()
                raise RuntimeError("browser connection lost; it will restart on the next action")
            while True:
                try:
                    line = self.q.get(timeout=timeout)
                except queue.Empty:
                    self._kill()
                    raise RuntimeError(f"browser timed out after {timeout}s")
                if line is None:
                    self._kill()
                    raise RuntimeError("browser stopped unexpectedly")
                r = json.loads(line)
                if "ready" in r:
                    continue
                if r.get("url") is not None:
                    self.last = {"url": r.get("url", ""), "title": r.get("title", "")}
                if not r.get("ok"):
                    self.error = r.get("error", "")
                return r

    def shot_png(self, full: bool = False) -> bytes:
        r = self.cmd("shot", full=full)
        if not r.get("ok") or not r.get("png"):
            raise RuntimeError(r.get("error") or "no screenshot")
        return base64.b64decode(r["png"])

    def stop(self) -> None:
        with self.lock:
            if self.proc and self.proc.poll() is None:
                try:
                    self.proc.stdin.write(json.dumps({"op": "close"}) + "\n"); self.proc.stdin.flush()
                    time.sleep(0.2)
                except OSError:
                    pass
            self._kill()
            self.last = {"url": "", "title": ""}
