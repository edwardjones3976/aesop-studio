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

import os
import socket

REPO = Path(__file__).resolve().parent.parent
WORKER = Path(__file__).with_name("browser_worker.py")
LAUNCH_TIMEOUT = 60
CMD_TIMEOUT = 45
CDP_PORT = 9222
NEW_GROUP = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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


def _port_open(port: int) -> bool:
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
    def __init__(self, data_dir=None):
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.q: queue.Queue = queue.Queue()
        self.last = {"url": "", "title": ""}
        self.started_at = 0.0
        self.error = ""
        # A persistent profile so the owner's sign-ins and cookies survive restarts.
        base = Path(data_dir) if data_dir else REPO
        self.profile = str(base / "browser-profile")
        self.signin_proc: subprocess.Popen | None = None
        self.mode = "studio"          # "studio" = Studio's own profile; "chrome" = the owner's running Chrome via CDP
        self.cdp_url = f"http://127.0.0.1:{CDP_PORT}"

    # ---- availability ----
    def available(self) -> bool:
        return venv_python() is not None and WORKER.is_file()

    def signing_in(self) -> bool:
        return bool(self.signin_proc and self.signin_proc.poll() is None)

    def status(self) -> dict:
        return {"available": self.available(),
                "running": bool(self.proc and self.proc.poll() is None),
                "signing_in": self.signing_in(),
                "mode": self.mode,
                "chrome_found": chrome_exe() is not None,
                "chrome_connected": self.mode == "chrome" and _port_open(CDP_PORT),
                "url": self.last.get("url", ""), "title": self.last.get("title", ""),
                "error": self.error,
                "note": "" if self.available() else
                        "The browser needs Playwright + Chrome in the project's .venv. Run: "
                        ".venv\\Scripts\\python -m playwright install chrome"}

    # ---- use the owner's own Chrome (their real profile and logins) over the DevTools port ----
    def use_my_chrome(self, confirm_restart: bool = False) -> dict:
        if not chrome_exe():
            raise RuntimeError("Google Chrome was not found on this PC")
        with self.lock:
            self._kill()  # free our worker; the CDP worker will attach instead
            if _port_open(CDP_PORT):
                self.mode = "chrome"; self.error = ""
                return {"connected": True, "mode": "chrome", "note": "Connected to your Chrome."}
            if _chrome_running() and not confirm_restart:
                return {"needs_restart": True, "running": True, "mode": self.mode,
                        "note": "Your Chrome is open but without remote control. To use it, Studio must close and "
                                "reopen it with remote control on (your tabs are restored, your logins kept). Confirm to continue."}
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
                    return {"connected": False, "error": "Chrome would not close (a window may be asking to confirm). "
                                                         "Close all Chrome windows yourself, then try again."}
                time.sleep(0.5)
            try:
                subprocess.Popen([str(chrome_exe()), f"--remote-debugging-port={CDP_PORT}",
                                  f"--user-data-dir={chrome_user_data()}", "--restore-last-session"],
                                 creationflags=NEW_GROUP)
            except OSError as e:
                return {"connected": False, "error": f"could not launch Chrome: {type(e).__name__}"}
            for _ in range(60):
                if _port_open(CDP_PORT):
                    break
                time.sleep(0.25)
            if not _port_open(CDP_PORT):
                return {"connected": False, "error": "Chrome started but did not open its remote-control port. "
                                                     "Make sure all other Chrome windows are closed, then try again."}
            self.mode = "chrome"; self.error = ""
            return {"connected": True, "mode": "chrome", "note": "Connected to your Chrome (your profile and logins)."}

    def use_studio_chrome(self) -> dict:
        with self.lock:
            self._kill()
            self.mode = "studio"; self.error = ""
        return {"mode": "studio"}

    # ---- owner sign-in: a real window the owner uses by hand ----
    def sign_in(self, url: str = "") -> dict:
        py = venv_python()
        if not py:
            raise RuntimeError("browser unavailable: no project .venv Python with Playwright")
        with self.lock:
            if self.signing_in():
                return {"signing_in": True, "note": "a sign-in window is already open"}
            self._kill()  # free the profile lock: only one process may use it at a time
            time.sleep(0.3)
            args = [str(py), "-I", str(WORKER), self.profile, "--signin", url or "about:blank"]
            self.signin_proc = subprocess.Popen(args, cwd=str(REPO), creationflags=NEW_GROUP)
        return {"signing_in": True, "note": "A browser window opened on your desktop. Sign in there, then close "
                                            "the window — your session is saved for the panel and the providers."}

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
        if self.signing_in():
            raise RuntimeError("finish signing in first (close the sign-in window on your desktop)")
        py = venv_python()
        if not py:
            raise RuntimeError("browser unavailable: no project .venv Python with Playwright")
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break
        if self.mode == "chrome":
            if not _port_open(CDP_PORT):
                self.mode = "studio"
                raise RuntimeError("your Chrome is no longer connected (its window was closed); switched back to "
                                   "Studio's browser — use “Use my Chrome” to reconnect")
            worker_args = ["--cdp", self.cdp_url]
        else:
            worker_args = [self.profile]
        self.proc = subprocess.Popen([str(py), "-I", str(WORKER), *worker_args], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=str(REPO), text=True,
                                     encoding="utf-8", bufsize=1, creationflags=NEW_GROUP)
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
            if self.signin_proc and self.signin_proc.poll() is None:
                try:
                    self.signin_proc.kill()
                except OSError:
                    pass
            self.signin_proc = None
            self.last = {"url": "", "title": ""}
