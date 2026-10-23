"""Aesop Studio login app: start the local server, open a one-time sign-in link, pin a Desktop shortcut."""
from __future__ import annotations

import os
import struct
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PORT = int(os.environ.get("AESOP_PORT", 8765))
DATA = Path(os.environ.get("AESOP_DATA", Path(os.environ.get("LOCALAPPDATA", ".")) / "AesopStudio"))
PID_FILE = DATA / "server.pid"
LINK_FILE = DATA / "launch-link.txt"
RELOGIN = DATA / "relogin.request"
ICON_FILE = ROOT / "tools" / "aesop.ico"
SHORTCUT_NAME = "Aesop Studio.lnk"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def console_python() -> str:
    p = Path(sys.executable)
    if p.name.lower() == "pythonw.exe":
        c = p.with_name("python.exe")
        if c.is_file():
            return str(c)
    return sys.executable


def windowed_python() -> str:
    p = Path(sys.executable)
    w = p.with_name("pythonw.exe")
    return str(w if w.is_file() else p)


def _pid_alive(pid: int) -> bool:
    """Windows: os.kill(pid, 0) is not a reliable existence check."""
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    try:
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                           capture_output=True, text=True, timeout=15, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return f'"{pid}"' in r.stdout


def parse_listener(netstat_text: str, port: int = PORT) -> int | None:
    want = {f"127.0.0.1:{port}", f"[::1]:{port}"}
    for line in netstat_text.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[-2].upper() != "LISTENING":
            continue
        if parts[1] in want:
            try:
                return int(parts[-1])
            except ValueError:
                return None
    return None


def _listener_pid(port: int = PORT) -> int | None:
    """PID listening on loopback:port, if any."""
    try:
        r = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, timeout=15,
                           creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_listener(r.stdout, port)


def studio_pid() -> int | None:
    """Live Studio process: recorded pid if still running, else whoever holds the loopback port."""
    if PID_FILE.is_file():
        try:
            pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = None
        else:
            if _pid_alive(pid):
                return pid
    listen = _listener_pid()
    if listen:
        try:
            PID_FILE.write_text(str(listen), encoding="utf-8")
        except OSError:
            pass
        return listen
    return None


def last_server_error() -> str:
    err = DATA / "server.log.err"
    try:
        text = err.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        text = ""
    return text.splitlines()[-1] if text else ""


def desktop_dir() -> Path:
    home = Path.home() / "Desktop"
    if home.is_dir():
        return home
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"


def write_icon(path: Path = ICON_FILE) -> Path:
    """16×16 32-bit ICO of the Studio mark (no extra packages)."""
    w = h = 16
    pixels = bytearray()
    for y in range(h - 1, -1, -1):
        for x in range(w):
            inside = 1 <= x <= 14 and 1 <= y <= 14
            dx, dy = x - 8, y - 8
            ring = 25 <= dx * dx + dy * dy <= 49
            stem = 7 <= x <= 8 and 4 <= y <= 12
            bar = 5 <= x <= 10 and 8 <= y <= 9
            if not inside:
                pixels += b"\x00\x00\x00\x00"
            elif ring or stem or bar:
                pixels += b"\x6c\x91\xff\xff"  # BGRA coral
            else:
                pixels += b"\x1c\x18\x16\xff"
    and_row = b"\x00\x00\x00\x00"
    xor_and = bytes(pixels) + and_row * h
    dib = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, len(xor_and), 0, 0, 0, 0) + xor_and
    entry = struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(dib), 22)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00\x00\x01\x00\x01\x00" + entry + dib)
    return path


def install_shortcut(desktop: Path | None = None) -> Path:
    desk = desktop or desktop_dir()
    desk.mkdir(parents=True, exist_ok=True)
    ico = write_icon()
    lnk = desk / SHORTCUT_NAME
    target = windowed_python()
    args = f'"{Path(__file__).resolve()}"'
    work = str(ROOT)
    ps = (
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({_ps_lit(str(lnk))}); "
        f"$s.TargetPath = {_ps_lit(target)}; $s.Arguments = {_ps_lit(args)}; "
        f"$s.WorkingDirectory = {_ps_lit(work)}; $s.WindowStyle = 7; "
        f"$s.Description = 'Sign in to Aesop Studio on this PC'; "
        f"$s.IconLocation = {_ps_lit(str(ico))}; $s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps], check=True,
                   creationflags=CREATE_NO_WINDOW)
    if not lnk.is_file():
        raise RuntimeError(f"shortcut was not created at {lnk}")
    return lnk


def _ps_lit(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def start_server() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    if studio_pid():
        return
    log, err = DATA / "server.log", DATA / "server.log.err"
    LINK_FILE.unlink(missing_ok=True)
    proc = subprocess.Popen(
        [console_python(), "-m", "aesop_studio", "--port", str(PORT), "--data", str(DATA)],
        cwd=str(ROOT), stdout=log.open("w", encoding="utf-8"),
        stderr=err.open("w", encoding="utf-8"), creationflags=CREATE_NO_WINDOW)
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    for _ in range(20):
        code = proc.poll()
        if code is not None:
            detail = last_server_error() or f"server exited {code}"
            raise RuntimeError(detail)
        if LINK_FILE.is_file():
            return
        time.sleep(0.25)


def wait_link(previous: str = "", timeout: float = 90.0) -> str:
    end = time.time() + timeout
    while time.time() < end:
        if LINK_FILE.is_file():
            now = LINK_FILE.read_text(encoding="utf-8").strip()
            if now.startswith("http://127.0.0.1:") and now != previous:
                return now
        err = last_server_error()
        if err and "not started" in err.lower():
            raise RuntimeError(err)
        time.sleep(0.2)
    detail = last_server_error()
    raise TimeoutError(detail or "Studio did not issue a sign-in link. Is it already running from another window?")


def request_relogin() -> str:
    previous = LINK_FILE.read_text(encoding="utf-8").strip() if LINK_FILE.is_file() else ""
    RELOGIN.write_text("1", encoding="utf-8")
    return wait_link(previous, timeout=15.0)


def sign_in() -> str:
    """Start Studio if needed and open a fresh one-time login link in the browser."""
    if studio_pid():
        url = request_relogin()
    else:
        try:
            start_server()
            url = wait_link("")
        except RuntimeError as e:
            if studio_pid():
                url = request_relogin()
            else:
                raise e
    webbrowser.open(url)
    return url.split("?", 1)[0]


def stop_server() -> None:
    pid = studio_pid()
    if pid:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                       creationflags=CREATE_NO_WINDOW)
    PID_FILE.unlink(missing_ok=True)
    LINK_FILE.unlink(missing_ok=True)


def run_gui() -> None:
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.title("Aesop Studio")
    root.configure(bg="#161412")
    root.resizable(False, False)
    root.geometry("380x240")
    try:
        root.iconbitmap(str(write_icon()))
    except tk.TclError:
        pass

    status = tk.StringVar(value="Starting…")
    tk.Label(root, text="Aesop Studio", fg="#ece7df", bg="#161412",
             font=("Segoe UI", 16, "bold")).pack(pady=(22, 4))
    tk.Label(root, text="Local sign-in for this PC. Loopback only.",
             fg="#a39b8f", bg="#161412", font=("Segoe UI", 9)).pack()
    tk.Label(root, textvariable=status, fg="#ff916c", bg="#161412",
             font=("Segoe UI", 10), wraplength=340, justify="center").pack(pady=16)

    def set_status(msg: str) -> None:
        status.set(msg)
        root.update_idletasks()

    def do_login() -> None:
        try:
            set_status("Opening a one-time sign-in link…")
            host = sign_in()
            set_status(f"Signed-in browser opened.\n{host}")
        except Exception as e:
            set_status(str(e))
            messagebox.showerror("Aesop Studio", str(e))

    def do_stop() -> None:
        stop_server()
        set_status("Studio stopped.")

    row = tk.Frame(root, bg="#161412")
    row.pack(pady=8)
    tk.Button(row, text="Sign in", command=do_login, bg="#ff916c", fg="#1a1410",
              activebackground="#ffb090", relief="flat", padx=18, pady=8,
              font=("Segoe UI", 10, "bold")).pack(side="left", padx=6)
    tk.Button(row, text="Stop", command=do_stop, bg="#2a2622", fg="#ece7df",
              activebackground="#3a342e", relief="flat", padx=18, pady=8,
              font=("Segoe UI", 10)).pack(side="left", padx=6)
    root.after(80, do_login)
    root.mainloop()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    install_only = "--install-shortcut" in argv
    lnk = install_shortcut()
    if install_only:
        print(lnk)
        return 0
    run_gui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
