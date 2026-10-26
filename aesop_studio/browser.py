"""Studio-side manager for Browser v2: Chrome Extension Bridge (primary) + DevTools worker fallback.

Browser v2 connects to the owner's normal Chrome profile through the Manifest V3 extension in `extension/`,
authenticated over 127.0.0.1 with a per-server cryptographic pairing token (`X-Aesop-Bridge-Token`).
Because it runs inside the owner's normal Chrome profile, all existing Google, GitHub, and other logins work
immediately with no re-sign-in, no Chrome restart, and no second profile.

When the extension is not paired, `Browser` preserves fallback compatibility with the Playwright worker over CDP.
"""
from __future__ import annotations

import base64
import hmac
import json
import os
import queue
import re
import secrets
import socket
import subprocess
import threading
import time
from pathlib import Path

from .security import redact, sanitize_url

REPO = Path(__file__).resolve().parent.parent
EXTENSION_DIR = REPO / "extension"
WORKER = Path(__file__).with_name("browser_worker.py")
LAUNCH_TIMEOUT = 60
CMD_TIMEOUT = 45
CDP_PORT = 9222
BRIDGE_TTL = 15.0
NEW_GROUP = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NOT_CONNECTED = "your Chrome isn't connected to Studio yet"

# Minimal 1x1 transparent PNG fallback when a background tab cannot be screen-captured yet
_FALLBACK_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

_PURCHASE_RE = re.compile(
    r"\b(buy now|place your order|place order|complete purchase|pay now|confirm payment|submit order|one-click buy)\b",
    re.I,
)
_CAPTCHA_RE = re.compile(r"\b(captcha|recaptcha|hcaptcha|cf-turnstile|g-recaptcha)\b", re.I)
_PASSWORD_RE = re.compile(r"\b(password|passwd|passcode)\b", re.I)


def _repo_roots() -> list[Path]:
    roots = [REPO]
    git_p = REPO / ".git"
    try:
        if git_p.is_file():
            txt = git_p.read_text(encoding="utf-8", errors="ignore").strip()
            if txt.startswith("gitdir:"):
                gd = Path(txt.split(":", 1)[1].strip())
                if not gd.is_absolute():
                    gd = (REPO / gd).resolve()
                for cand in (gd.parent.parent.parent, REPO.parent / "Aesop-Studio"):
                    if cand.is_dir() and cand not in roots:
                        roots.append(cand)
    except OSError:
        pass
    return roots


def venv_python() -> Path | None:
    for root in _repo_roots():
        for c in (
            root / ".venv" / "Scripts" / "python.exe",
            root / ".venv" / "bin" / "python",
            root / "venv" / "Scripts" / "python.exe",
        ):
            if c.is_file():
                return c
    return None


def chrome_exe() -> Path | None:
    for c in (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ):
        if c.is_file():
            return c
    return None


def studio_chrome_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "C:/")) / "AesopStudio" / "chrome-studio"


CHROME_ARGS = [
    "--remote-debugging-port={port}",
    "--user-data-dir={udd}",
    "--no-first-run",
    "--no-default-browser-check",
    "--restore-last-session",
]


def launch_studio_chrome() -> None:
    udd = studio_chrome_dir()
    udd.mkdir(parents=True, exist_ok=True)
    args = [str(chrome_exe())] + [a.format(port=CDP_PORT, udd=udd) for a in CHROME_ARGS]
    subprocess.Popen(args, creationflags=NEW_GROUP)


def _port_open(port: int = CDP_PORT) -> bool:
    s = socket.socket()
    s.settimeout(0.4)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _chrome_running() -> bool:
    if os.name != "nt":
        return False
    try:
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=NEW_GROUP,
        )
        return "chrome.exe" in (r.stdout or "")
    except (OSError, subprocess.TimeoutExpired):
        return False


def _sanitize_element(el: dict, idx: int) -> dict:
    role = str(el.get("role") or el.get("tag") or "element")[:30]
    tag = str(el.get("tag") or "div")[:20]
    etype = str(el.get("type") or "").lower()[:30]
    raw_label = str(el.get("label") or el.get("text") or "").strip()
    is_pw = bool(
        el.get("is_password")
        or etype == "password"
        or _PASSWORD_RE.search(raw_label)
    )
    label = "[password field]" if is_pw else redact(raw_label[:140])
    href = sanitize_url(str(el.get("href") or ""))[:300] if el.get("href") else ""
    is_cap = bool(el.get("is_captcha") or _CAPTCHA_RE.search(raw_label))
    is_pur = bool(el.get("is_purchase") or _PURCHASE_RE.search(raw_label))
    raw_box = el.get("bbox") if isinstance(el.get("bbox"), dict) else (el.get("rect") if isinstance(el.get("rect"), dict) else {})
    bx = int(raw_box.get("x", raw_box.get("left", 0)) or 0)
    by = int(raw_box.get("y", raw_box.get("top", 0)) or 0)
    bw = int(raw_box.get("w") or 0)
    bh = int(raw_box.get("h") or 0)
    val = "[password field]" if is_pw else redact(str(el.get("value") or "")[:120])
    return {
        "ref": int(el.get("ref") or (idx + 1)),
        "role": role,
        "tag": tag,
        "type": "password" if is_pw else etype,
        "label": label,
        "value": val,
        "href": href,
        "bbox": {"x": bx, "y": by, "w": bw, "h": bh},
        "rect": {"x": bx, "y": by, "left": bx, "top": by, "w": bw, "h": bh},
        "in_viewport": bool(el.get("in_viewport", True)),
        "is_password": is_pw,
        "is_captcha": is_cap,
        "is_purchase": is_pur,
    }


def _sanitize_snapshot(raw: dict) -> dict:
    url = sanitize_url(str(raw.get("url") or "")) if raw.get("url") else ""
    title = redact(str(raw.get("title") or "")[:240])
    vw = max(200, int(raw.get("vw") or 1366))
    vh = max(200, int(raw.get("vh") or 854))
    headings = []
    for h in (raw.get("headings") or [])[:40]:
        if isinstance(h, dict) and h.get("text"):
            headings.append({"level": int(h.get("level") or 1), "text": redact(str(h["text"])[:160])})
    elements = [
        _sanitize_element(e, i)
        for i, e in enumerate((raw.get("elements") or [])[:90])
        if isinstance(e, dict)
    ]
    forms = []
    for f in (raw.get("forms") or [])[:15]:
        if not isinstance(f, dict):
            continue
        fields = []
        for fld in (f.get("fields") or [])[:20]:
            if isinstance(fld, dict):
                pw = bool(fld.get("is_password") or str(fld.get("type") or "").lower() == "password")
                fields.append({
                    "ref": fld.get("ref"),
                    "role": str(fld.get("role") or "textbox")[:30],
                    "type": "password" if pw else str(fld.get("type") or "")[:30],
                    "label": "[password field]" if pw else redact(str(fld.get("label") or "")[:120]),
                    "is_password": pw,
                })
        forms.append({
            "index": int(f.get("index") or (len(forms) + 1)),
            "name": redact(str(f.get("name") or f"form-{len(forms) + 1}")[:80]),
            "fields": fields,
        })
    links = []
    for lk in (raw.get("links") or [])[:120]:
        if isinstance(lk, dict) and lk.get("href"):
            href = sanitize_url(str(lk["href"]))
            if href.startswith(("http://", "https://")):
                links.append({
                    "ref": lk.get("ref"),
                    "text": redact(str(lk.get("text") or "")[:100]),
                    "href": href[:300],
                })
    text = redact(str(raw.get("text") or "")[:40_000])
    main_text = redact(str(raw.get("main_text") or text)[:24_000])
    tabs = []
    for tb in (raw.get("tabs") or [])[:30]:
        if isinstance(tb, dict):
            tabs.append({
                "id": tb.get("id"),
                "title": redact(str(tb.get("title") or "")[:160]),
                "url": sanitize_url(str(tb.get("url") or ""))[:300],
                "active": bool(tb.get("active")),
                "selected": bool(tb.get("selected")),
            })
    return {
        "ok": bool(raw.get("ok", True)),
        "error": redact(str(raw.get("error") or "")[:300]),
        "url": url,
        "title": title,
        "vw": vw,
        "vh": vh,
        "scrollY": int(raw.get("scrollY") or 0),
        "docH": int(raw.get("docH") or vh),
        "headings": headings,
        "elements": elements,
        "forms": forms,
        "links": links,
        "main_text": main_text,
        "text": text,
        "tabs": tabs,
        "tab_id": raw.get("tab_id"),
    }


class Browser:
    def __init__(self, data_dir=None):
        self.lock = threading.Lock()
        self.ext_lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.q: queue.Queue = queue.Queue()
        self.last = {"url": "", "title": ""}
        self.error = ""
        self.cdp_url = f"http://127.0.0.1:{CDP_PORT}"

        # v2 Extension Bridge state (persistent token in data_dir when provided)
        self.data_dir: Path | None = Path(data_dir).resolve() if data_dir else None
        self.token_path: Path | None = (self.data_dir / "browser_pairing.token") if self.data_dir else None
        self.pairing_token: str = self._load_or_create_token()
        self.ext_last_seen: float = 0.0
        self.ext_cmd_q: queue.Queue = queue.Queue()
        self.ext_pending: dict[str, dict] = {}
        self.ext_state: dict = _sanitize_snapshot({})
        self.last_png: bytes = b""
        self.last_dims: tuple[int, int] = (1366, 854)
        self.frame_seq: int = 0
        self.state_seq: int = 0

    # ---- Pairing & Extension Bridge ----
    def _load_or_create_token(self) -> str:
        if self.token_path is not None:
            try:
                if self.token_path.is_file() and not self.token_path.is_symlink():
                    existing = self.token_path.read_text(encoding="utf-8").strip()
                    if len(existing) >= 24:
                        return existing
            except OSError:
                pass
        tok = secrets.token_urlsafe(32)
        self._write_token_file(tok)
        return tok

    def _write_token_file(self, token: str) -> None:
        if self.token_path is None:
            return
        try:
            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.token_path.with_suffix(".tmp")
            fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                os.write(fd, (token + "\n").encode("utf-8"))
            finally:
                os.close(fd)
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, self.token_path)
            try:
                os.chmod(self.token_path, 0o600)
            except OSError:
                pass
            if os.name == "nt":
                user = os.environ.get("USERNAME")
                domain = os.environ.get("USERDOMAIN")
                principal = f"{domain}\\{user}" if domain and user else user
                if principal:
                    subprocess.run(
                        ["icacls", str(self.token_path), "/inheritance:r", "/grant:r", f"{principal}:(R,W)"],
                        capture_output=True,
                        timeout=5,
                        creationflags=NEW_GROUP,
                    )
        except (OSError, subprocess.SubprocessError):
            pass

    def verify_token(self, token: str | None) -> bool:
        tok = str(token or "").strip()
        return bool(tok) and hmac.compare_digest(self.pairing_token, tok)

    def rotate_token(self) -> str:
        with self.ext_lock:
            self.pairing_token = secrets.token_urlsafe(32)
            self._write_token_file(self.pairing_token)
            return self.pairing_token

    def pairing_info(self, port: int = 8765) -> dict:
        return {
            "pairing_token": self.pairing_token,
            "pairing_code": f"127.0.0.1:{port}#{self.pairing_token}",
            "port": port,
            "extension_dir": str(EXTENSION_DIR),
            "extension_connected": self.extension_connected(),
        }

    def extension_connected(self) -> bool:
        return (time.time() - self.ext_last_seen) < BRIDGE_TTL

    def _ingest_ext_state(self, raw: dict) -> dict:
        snap = _sanitize_snapshot(raw)
        with self.ext_lock:
            self.ext_last_seen = time.time()
            # Keep previous elements/text if a lightweight update omitted them
            if not snap["elements"] and self.ext_state.get("elements") and snap["url"] == self.ext_state.get("url"):
                if "elements" not in raw:
                    snap["elements"] = self.ext_state["elements"]
            if not snap["text"] and self.ext_state.get("text") and snap["url"] == self.ext_state.get("url"):
                if "text" not in raw:
                    snap["text"] = self.ext_state["text"]
                    snap["main_text"] = self.ext_state.get("main_text", "")
            if not snap["tabs"] and self.ext_state.get("tabs") and "tabs" not in raw:
                snap["tabs"] = self.ext_state["tabs"]
            self.ext_state = snap
            if snap["url"] or snap["title"]:
                self.last = {"url": snap["url"], "title": snap["title"]}
            self.error = snap["error"]
            self.state_seq += 1
            png_b64 = raw.get("png")
            if isinstance(png_b64, str) and png_b64:
                try:
                    decoded = base64.b64decode(png_b64)
                    if decoded.startswith(b"\x89PNG"):
                        self.last_png = decoded
                        self.last_dims = (snap["vw"], snap["vh"])
                        self.frame_seq += 1
                except ValueError:
                    pass
            elif isinstance(png_b64, (bytes, bytearray)) and bytes(png_b64).startswith(b"\x89PNG"):
                self.last_png = bytes(png_b64)
                self.last_dims = (snap["vw"], snap["vh"])
                self.frame_seq += 1
        return snap

    def bridge_push(self, payload: dict) -> dict:
        snap = self._ingest_ext_state(payload or {})
        return {"ok": True, "state_seq": self.state_seq, "frame_seq": self.frame_seq, "url": snap["url"]}

    def bridge_poll(self, wait_s: float = 1.5) -> dict:
        with self.ext_lock:
            self.ext_last_seen = time.time()
        try:
            cmd = self.ext_cmd_q.get(timeout=max(0.01, min(5.0, float(wait_s))))
            return {"ok": True, "cmd": cmd}
        except queue.Empty:
            return {"ok": True, "cmd": None}

    def bridge_reply(self, cmd_id: str, result: dict) -> dict:
        snap = self._ingest_ext_state(result or {})
        with self.ext_lock:
            slot = self.ext_pending.get(str(cmd_id or ""))
            if slot is not None:
                merged = {**snap}
                if "matches" in (result or {}):
                    merged["matches"] = [
                        {"line": int(m.get("line") or 0), "snippet": redact(str(m.get("snippet") or "")[:220])}
                        for m in (result.get("matches") or [])[:25]
                        if isinstance(m, dict)
                    ]
                if "element_matches" in (result or {}):
                    merged["element_matches"] = [
                        _sanitize_element(e, i)
                        for i, e in enumerate((result.get("element_matches") or [])[:20])
                        if isinstance(e, dict)
                    ]
                slot["result"] = merged
                slot["event"].set()
        return {"ok": True}

    # ---- Status & Availability ----
    def available(self) -> bool:
        if self.extension_connected():
            return True
        return venv_python() is not None and WORKER.is_file()

    def connected(self) -> bool:
        return self.extension_connected() or _port_open()

    def mode(self) -> str:
        if self.extension_connected():
            return "extension"
        if _port_open():
            return "cdp"
        return "disconnected"

    def status(self) -> dict:
        ext_conn = self.extension_connected()
        cdp_conn = _port_open()
        avail = self.available()
        return {
            "available": avail,
            "extension_available": EXTENSION_DIR.is_dir(),
            "extension_dir": str(EXTENSION_DIR),
            "extension_connected": ext_conn,
            "connected": ext_conn or cdp_conn,
            "mode": "extension" if ext_conn else ("cdp" if cdp_conn else "disconnected"),
            "running": ext_conn or bool(self.proc and self.proc.poll() is None),
            "chrome_found": chrome_exe() is not None,
            "url": self.last.get("url", ""),
            "title": self.last.get("title", ""),
            "error": self.error,
            "frame_seq": self.frame_seq,
            "state_seq": self.state_seq,
            "tabs": self.ext_state.get("tabs", []),
            "note": ""
            if (avail or EXTENSION_DIR.is_dir())
            else "The browser needs Playwright in the project's .venv. Run: "
                 ".venv\\Scripts\\python -m playwright install chrome",
        }

    def live_state(self) -> dict:
        """Lightweight state + structural elements for the live Browser panel in Studio."""
        st = self.status()
        snap = self.ext_state
        return {
            **st,
            "vw": snap.get("vw", self.last_dims[0]),
            "vh": snap.get("vh", self.last_dims[1]),
            "scrollY": snap.get("scrollY", 0),
            "docH": snap.get("docH", self.last_dims[1]),
            "headings": snap.get("headings", [])[:30],
            "elements": snap.get("elements", [])[:60],
            "forms": snap.get("forms", [])[:10],
            "links": snap.get("links", [])[:60],
            "main_text": (snap.get("main_text") or "")[:8000],
        }

    # ---- Connecting ----
    def connect(self, confirm_restart: bool = False) -> dict:
        if self.extension_connected():
            self.error = ""
            return {
                "connected": True,
                "mode": "extension",
                "note": "Connected to your normal Chrome via the Aesop Studio extension (existing logins active).",
            }
        if not chrome_exe():
            raise RuntimeError("Google Chrome was not found on this PC")
        with self.lock:
            if _port_open():
                self.error = ""
                return {"connected": True, "mode": "cdp", "note": "Connected to your Studio Chrome window."}
            self._kill()
            launch_studio_chrome()
            for _ in range(60):
                if _port_open():
                    break
                time.sleep(0.25)
            if not _port_open():
                return {
                    "connected": False,
                    "error": "The Studio Chrome window did not open its link. Load the unpacked extension from "
                             f"{EXTENSION_DIR} in your normal Chrome, or close any stale Studio Chrome window.",
                }
            self.error = ""
            return {
                "connected": True,
                "opened": True,
                "mode": "cdp",
                "note": "A Chrome window opened — that's Studio's browser. Sign into sites there once "
                        "(GitHub, anything); it stays signed in.",
            }

    # ---- Safety enforcement on agent actions ----
    def _check_agent_safety(self, op: str, args: dict) -> str | None:
        if not args.get("agent"):
            return None
        elements = self.ext_state.get("elements") or []
        if op in ("click_ref", "fill_ref"):
            ref = int(args.get("ref") or 0)
            target = next((e for e in elements if int(e.get("ref") or 0) == ref), None)
            if target:
                if target.get("is_password") or target.get("type") == "password":
                    return "refused: a provider cannot type into a password field"
                if target.get("is_captcha"):
                    return "refused: a provider cannot solve CAPTCHAs"
                if target.get("is_purchase"):
                    return "refused: a provider cannot make purchases or enter payment details"
        if op == "click" and "x" in args and "y" in args:
            x, y = float(args["x"]), float(args["y"])
            for e in elements:
                r = e.get("bbox") or e.get("rect") or {}
                left, top, w, h = r.get("left", r.get("x", 0)), r.get("top", r.get("y", 0)), r.get("w", 0), r.get("h", 0)
                if w > 0 and h > 0 and left <= x <= left + w and top <= y <= top + h:
                    if e.get("is_password"):
                        return "refused: a provider cannot type into a password field"
                    if e.get("is_captcha"):
                        return "refused: a provider cannot solve CAPTCHAs"
                    if e.get("is_purchase"):
                        return "refused: a provider cannot make purchases or enter payment details"
        if op in ("type", "fill_ref"):
            txt = str(args.get("text") or "")
            if _PURCHASE_RE.search(txt):
                return "refused: a provider cannot make purchases or enter payment details"
        return None

    # ---- Extension command dispatch ----
    def _ext_cmd(self, op: str, timeout: float = 12.0, **args) -> dict:
        safety_err = self._check_agent_safety(op, args)
        if safety_err:
            self.error = safety_err
            return {"ok": False, "error": safety_err, **self.last}

        if op in ("navigate", "new_tab"):
            url = str(args.get("url") or "").strip()
            if not url:
                return {"ok": False, "error": "no url", **self.last}
            if "://" not in url:
                url = "https://" + url
            if not url.lower().startswith(("http://", "https://")):
                return {"ok": False, "error": "only http(s) pages are allowed", **self.last}
            args["url"] = url

        cmd_id = f"cmd_{secrets.token_hex(6)}"
        ev = threading.Event()
        slot = {"event": ev, "result": None}
        with self.ext_lock:
            self.ext_pending[cmd_id] = slot
        self.ext_cmd_q.put({"id": cmd_id, "op": op, **args})

        # For read-only state queries, wait briefly for a live refresh; if no live poller is active
        # (e.g. right after a push or in offline tests), return the latest pushed state immediately.
        wait_time = 0.25 if op in ("ping", "text", "links", "snapshot", "tabs") else min(timeout, 12.0)
        signalled = ev.wait(timeout=wait_time)
        with self.ext_lock:
            self.ext_pending.pop(cmd_id, None)

        if signalled and slot["result"] is not None:
            return slot["result"]

        # Fallback to pushed state for read-only ops or in-memory state updates
        snap = dict(self.ext_state)
        if op == "find":
            q = str(args.get("query") or "").strip().lower()
            lines = (snap.get("text") or "").splitlines()
            matches = [
                {"line": i + 1, "snippet": line.strip()[:220]}
                for i, line in enumerate(lines)
                if q and q in line.lower()
            ][:25]
            el_matches = [
                e for e in (snap.get("elements") or [])
                if q and (q in (e.get("label") or "").lower() or q in (e.get("href") or "").lower())
            ][:20]
            return {**snap, "ok": True, "matches": matches, "element_matches": el_matches}
        if op in ("ping", "text", "links", "snapshot", "tabs"):
            return {**snap, "ok": True}
        if not signalled:
            # Update optimistic URL on navigate if no live extension worker replied within wait_time
            if op == "navigate" and args.get("url"):
                u = sanitize_url(args["url"])
                self.last["url"] = u
                self.ext_state["url"] = u
            return {**snap, "ok": True, **self.last}
        return {**snap, "ok": True}

    # ---- Worker lifecycle (CDP fallback) ----
    def _reader(self, proc):
        for line in proc.stdout:
            line = line.strip()
            if line:
                self.q.put(line)
        self.q.put(None)

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
        self.proc = subprocess.Popen(
            [str(py), "-I", str(WORKER), "--cdp", self.cdp_url],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=str(REPO),
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=NEW_GROUP,
        )
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
        if self.extension_connected():
            return self._ext_cmd(op, timeout=timeout, **args)

        safety_err = self._check_agent_safety(op, args)
        if safety_err:
            self.error = safety_err
            return {"ok": False, "error": safety_err, **self.last}

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
                    raise RuntimeError(
                        NOT_CONNECTED
                        if not _port_open()
                        else "the browser link stopped; it reconnects on the next action"
                    )
                r = json.loads(line)
                if "ready" in r:
                    continue
                if r.get("url") is not None:
                    self.last = {"url": sanitize_url(r.get("url", "")), "title": redact(r.get("title", ""))}
                if "elements" in r or "text" in r:
                    snap = _sanitize_snapshot(r)
                    self.ext_state = snap
                    self.state_seq += 1
                if not r.get("ok"):
                    self.error = redact(r.get("error", ""))
                    if not _port_open():
                        self._kill()
                        raise RuntimeError(NOT_CONNECTED)
                return r

    def snapshot(self) -> dict:
        """Return a structured DOM + Accessibility snapshot of the current page."""
        r = self.cmd("snapshot")
        if "elements" not in r:
            txt = self.cmd("text") if "text" not in r else r
            lks = self.cmd("links") if "links" not in r else r
            merged = {**r, "text": txt.get("text", ""), "links": lks.get("links", [])}
            return _sanitize_snapshot(merged)
        return _sanitize_snapshot(r)

    def shot(self, full: bool = False) -> dict:
        """{"png": bytes, "vw": int, "vh": int, "url", "title", "seq": int} of Studio's active tab."""
        if self.extension_connected():
            # Request a fresh capture if none cached or if full capture requested
            if not self.last_png or full:
                self._ext_cmd("shot", timeout=0.25, full=full)
            png = self.last_png or _FALLBACK_PNG
            vw, vh = self.last_dims
            return {
                "png": png,
                "vw": vw,
                "vh": vh,
                "url": self.last.get("url", ""),
                "title": self.last.get("title", ""),
                "seq": self.frame_seq,
            }
        r = self.cmd("shot", full=full)
        if not r.get("ok") or not r.get("png"):
            raise RuntimeError(r.get("error") or "no screenshot")
        raw_png = base64.b64decode(r["png"])
        self.last_png = raw_png
        self.last_dims = (r.get("vw") or 1366, r.get("vh") or 854)
        self.frame_seq += 1
        return {
            "png": raw_png,
            "vw": self.last_dims[0],
            "vh": self.last_dims[1],
            "url": r.get("url", ""),
            "title": r.get("title", ""),
            "seq": self.frame_seq,
        }

    def shot_png(self, full: bool = False) -> bytes:
        return self.shot(full)["png"]

    def stop(self) -> None:
        with self.ext_lock:
            self.ext_last_seen = 0.0
            while not self.ext_cmd_q.empty():
                try:
                    self.ext_cmd_q.get_nowait()
                except queue.Empty:
                    break
        with self.lock:
            if self.proc and self.proc.poll() is None:
                try:
                    self.proc.stdin.write(json.dumps({"op": "close"}) + "\n")
                    self.proc.stdin.flush()
                    time.sleep(0.3)
                except OSError:
                    pass
            self._kill()
            self.last = {"url": "", "title": ""}
