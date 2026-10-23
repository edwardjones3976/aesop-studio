"""Login app: shortcut install helpers and ICO write (no GUI)."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ["AESOP_PROBE_OFFLINE"] = "1"
os.environ["AESOP_SIMULATED_ROUTE"] = "1"

import importlib.util

_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("aesop_login_app", _ROOT / "tools" / "login_app.py")
login_app = importlib.util.module_from_spec(_spec)
assert _spec.loader
_spec.loader.exec_module(login_app)  # noqa: E402


class TestLoginApp(unittest.TestCase):
    def test_icon_is_valid_ico(self):
        tmp = Path(tempfile.mkdtemp(prefix="aesop-ico-"))
        ico = login_app.write_icon(tmp / "aesop.ico")
        data = ico.read_bytes()
        self.assertTrue(data.startswith(b"\x00\x00\x01\x00\x01\x00"))
        self.assertGreater(len(data), 64)

    def test_ps_lit_escapes_quotes(self):
        self.assertEqual(login_app._ps_lit("O'Brien"), "'O''Brien'")

    def test_desktop_dir_exists_or_is_under_home(self):
        d = login_app.desktop_dir()
        self.assertTrue(str(d).endswith("Desktop"))

    def test_parse_listener_loopback(self):
        sample = (
            "  TCP    0.0.0.0:80             0.0.0.0:0              LISTENING       4\n"
            "  TCP    127.0.0.1:8765         0.0.0.0:0              LISTENING       65856\n"
            "  TCP    127.0.0.1:8765         127.0.0.1:9            TIME_WAIT       0\n"
        )
        self.assertEqual(login_app.parse_listener(sample, 8765), 65856)
        self.assertIsNone(login_app.parse_listener(sample, 9999))

    def test_stale_pid_file_is_not_running(self):
        self.assertFalse(login_app._pid_alive(1))  # System Idle is PID 0; 1 is unused on Windows


if __name__ == "__main__":
    unittest.main()
