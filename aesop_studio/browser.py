"""Studio-side manager for the owner's own Chrome (driven over the DevTools port by browser_worker).

There is exactly one browser: the owner's Chrome, with their profile, logins and extensions. Studio drives one tab
in it. A Chrome that is already running without the DevTools port cannot be attached to, so connect() offers —
with the owner's explicit confirmation — to close and reopen Chrome with the port on (tabs restored, logins kept).
The worker subprocess runs under the project's .venv Python, which has Playwright; every command is one request /
one reply, serialized with a timeout, so a slow page never blocks another caller.
"""
from __future__ import annotations

import base64
import json
import os
import queue
import socket
import subprocess
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKER = Path(__file__).with_name("browser_worker.py")
LAUNCH_TIMEOUT = 60
CMD_TIMEOUT = 45
CDP_PORT = 9222
NEW_GROUP = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NOT_CONNECTED = "your Chrome isn't connected to Studio yet"


def venv_python() -> Path | None:
    for c in (REPO / ".venv" / "Scripts" / "python.exe", REPO / ".venv" / "bin" / "python",
              REPO / "venv" / "Scripts" / "python.exe"):
        if c.is_file():
            return c
    return None


def chrome_exe() -> Path | None:
    for c in (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
              Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
              Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe"):
        if c.is_file():
            return c
    return None


def chrome_user_data() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/User Data"


def _port_open(port: int = CDP_PORT) -> bool:
    s = socket.socket(); s.settimeout(0.4)
    try:
        s.connect(("127.0.0.1", port)); return True
    except OSError:
        return False
    finally:
        s.close()


def _chrome_running() -> bool:
    if os.name != "nt":
        return False
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/NH"], capture_output=True, text=True,
                           timeout=10, creationflags=NEW_GROUP)
        return "chrome.exe" in (r.stdout or "")
    except (OSError, subprocess.TimeoutExpired):
        return False


class Browser:
    def __init__(self, data_dir=None):  # data_dir kept for call compatibility; nothing is stored any more
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.q: queue.Queue = queue.Queue()
        self.last = {"url": "", "title": ""}
        self.error = ""
        self.cdp_url = f"http://127.0.0.1:{CDP_PORT}"

    def available(self) -> bool:
        return venv_python() is not None and WORKER.is_file()

    def connected(self) -> bool:
        return _port_open()

    def status(self) -> dict:
        return {"available": self.available(), "connected": self.connected(),
                "running": bool(self.proc and self.proc.poll() is None),
                "chrome_found": chrome_exe() is not None, "chrome_running": _chrome_running(),
                "url": self.last.get("url", ""), "title": self.last.get("title", ""), "error": self.error,
                "note": "" if self.available() else
                        "The browser needs Playwright in the project's .venv. Run: "
                        ".venv\\Scripts\\python -m playwright install chrome"}

    # ---- connecting the owner's Chrome ----
    def connect(self, confirm_restart: bool = False) -> dict:
        if not chrome_exe():
            raise RuntimeError("Google Chrome was not found on this PC")
        with self.lock:
            if _port_open():
                self.error = ""
                return {"connected": True, "note": "Connected to your Chrome."}
            self._kill()
            if _chrome_running() and not confirm_restart:
                return {"needs_restart": True,
                        "note": "Chrome has to be reopened once with remote control on. Your tabs are restored and "
                                "your logins are kept — save anything unsaved first."}
            if _chrome_running():
                try:
                    subprocess.run(["taskkill", "/IM", "chrome.exe", "/T"], capture_output=True, timeout=15,
                                   creationflags=NEW_GROUP)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                for _ in range(40):
                    if not _chrome_running():
                        break
                    time.sleep(0.25)
                if _chrome_running():
                    return {"connected": False, "error": "Chrome would not close (a window may be asking you to "
                                                         "confirm something). Close every Chrome window, then try again."}
                time.sleep(0.5)
            try:
                subprocess.Popen([str(chrome_exe()), f"--remote-debugging-port={CDP_PORT}",
                                  f"--user-data-dir={chrome_user_data()}", "--restore-last-session"],
                                 creationflags=NEW_GROUP)
            except OSError as e:
                return {"connected": False, "error": f"could not launch Chrome: {type(e).__name__}"}
            for _ in range(60):
                if _port_open():
                    break
                time.sleep(0.25)
            if not _port_open():
                return {"connected": False, "error": "Chrome started but its remote-control port never opened. "
                                                     "Close every Chrome window and try again."}
            self.error = ""
            return {"connected": True, "note": "Connected to your Chrome — your logins and extensions are live."}

    # ---- worker lifecycle ----
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
        if not _port_open():
            raise RuntimeError(NOT_CONNECTED)
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break
        self.proc = subprocess.Popen([str(py), "-I", str(WORKER), "--cdp", self.cdp_url], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=str(REPO), text=True,
                                     encoding="utf-8", bufsize=1, creationflags=NEW_GROUP)
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()
        try:
            ready = self.q.get(timeout=LAUNCH_TIMEOUT)
        except queue.Empty:
            self._kill()
            raise RuntimeError("the browser link did not start within the time limit")
        if ready is None or not json.loads(ready).get("ready"):
            self._kill()
            raise RuntimeError("could not attach to your Chrome; reconnect it and try again")

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
                raise RuntimeError("the browser link dropped; it reconnects on the next action")
            while True:
                try:
                    line = self.q.get(timeout=timeout)
                except queue.Empty:
                    self._kill()
                    raise RuntimeError(f"the browser timed out after {timeout}s")
                if line is None:
                    self._kill()
                    raise RuntimeError(NOT_CONNECTED if not _port_open() else
                                       "the browser link stopped; it reconnects on the next action")
                r = json.loads(line)
                if "ready" in r:
                    continue
                if r.get("url") is not None:
                    self.last = {"url": r.get("url", ""), "title": r.get("title", "")}
                if not r.get("ok"):
                    self.error = r.get("error", "")
                    if not _port_open():  # Chrome itself is gone: report that, not the stale Playwright error
                        self._kill()
                        raise RuntimeError(NOT_CONNECTED)
                return r

    def shot(self, full: bool = False) -> dict:
        """{"png": bytes, "vw": int, "vh": int, "url", "title"} of Studio's tab in the owner's Chrome."""
        r = self.cmd("shot", full=full)
        if not r.get("ok") or not r.get("png"):
            raise RuntimeError(r.get("error") or "no screenshot")
        return {"png": base64.b64decode(r["png"]), "vw": r.get("vw") or 1366, "vh": r.get("vh") or 854,
                "url": r.get("url", ""), "title": r.get("title", "")}

    def shot_png(self, full: bool = False) -> bytes:
        return self.shot(full)["png"]

    def stop(self) -> None:
        with self.lock:
            if self.proc and self.proc.poll() is None:
                try:
                    self.proc.stdin.write(json.dumps({"op": "close"}) + "\n"); self.proc.stdin.flush()
                    time.sleep(0.3)
                except OSError:
                    pass
            self._kill()
            self.last = {"url": "", "title": ""}
