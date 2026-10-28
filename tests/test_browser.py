"""Browser drive: guards and action mapping (offline; no real Chrome, no provider calls)."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ["AESOP_SIMULATED_ROUTE"] = "1"
os.environ["AESOP_PROBE_OFFLINE"] = "1"

from aesop_studio import browse_agent, providers  # noqa: E402
from aesop_studio.services import Services  # noqa: E402
from aesop_studio.store import Store  # noqa: E402
from aesop_studio.tasks import Supervisor  # noqa: E402


class FakeBrowser:
    def __init__(self):
        self.calls = []

    def cmd(self, op, **a):
        self.calls.append((op, a))
        return {
            "ok": True,
            "url": a.get("url", "https://x/"),
            "title": "T",
            "text": "hello",
        }

    def shot_png(self, full=False):
        return b"\x89PNG"


class TestDrive(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-drv-"))
        (self.tmp / "p").mkdir()
        self.store = Store(self.tmp / "d")
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        providers.refresh(self.store)
        self.p = self.svc.create_project("P", str(self.tmp / "p"), "simulated")
        self.fb = FakeBrowser()
        self.d = browse_agent.Drive(self.store, self.sup, self.fb)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_start_guards(self):
        with self.assertRaises(ValueError):  # too short a goal
            self.d.start(self.p, "claude", "x")
        with self.assertRaises(ValueError):  # not a vision route
            self.d.start(self.p, "grok", "find the rules of bid whist")
        # vision route but file-sharing off for the project
        self.svc.update_project(self.p["id"], {"transfer_policy": {"claude": False}})
        p = self.svc.project(self.p["id"])
        with mock_vision(self.d, ["claude"]):
            with self.assertRaises(ValueError) as e:
                self.d.start(p, "claude", "find the rules of bid whist")
            self.assertIn("off for this project", str(e.exception))

    def test_action_mapping_and_clamp(self):
        self.assertEqual(
            self.d._do({"action": "navigate", "url": "example.com"}), "example.com"
        )
        self.d._do({"action": "click", "x": 99999, "y": -5})
        self.assertEqual(
            self.fb.calls[-1], ("click", {"x": 1366, "y": 0})
        )  # clamped to the viewport
        self.d._do({"action": "scroll", "dy": 400})
        self.assertEqual(self.fb.calls[-1][0], "scroll")
        self.d._do({"action": "key", "key": "Enter"})
        self.assertEqual(self.fb.calls[-1], ("key", {"key": "Enter"}))
        self.assertEqual(self.d._do({"action": "read"}), "(read the page)")
        self.d._do({"action": "type", "text": "hi"})
        self.assertTrue(
            self.fb.calls[-1][1].get("agent")
        )  # the provider's typing is flagged so passwords are refused

    def test_status_shape(self):
        st = self.d.status()
        self.assertFalse(st["active"])
        self.assertIn("vision_routes", st)


class TestBrowserVenv(unittest.TestCase):
    def test_venv_python_from_worktree_gitlink(self):
        from aesop_studio import browser

        with tempfile.TemporaryDirectory(prefix="aesop-wt-") as td:
            td = Path(td)
            main = td / "main"
            wt = td / "wt"
            main.mkdir()
            wt.mkdir()
            py = main / ".venv" / "Scripts" / "python.exe"
            py.parent.mkdir(parents=True)
            py.write_text("", encoding="utf-8")
            gd = main / ".git" / "worktrees" / "wt"
            gd.mkdir(parents=True)
            (wt / ".git").write_text(f"gitdir: {gd.as_posix()}\n", encoding="utf-8")
            with mock.patch.object(browser, "REPO", wt):
                self.assertEqual(browser.venv_python(), py)


class mock_vision:  # noqa: N801 - tiny context manager
    def __init__(self, drive, routes):
        self.drive, self.routes = drive, routes

    def __enter__(self):
        self._orig = self.drive.vision_routes
        self.drive.vision_routes = lambda: self.routes

    def __exit__(self, *a):
        self.drive.vision_routes = self._orig


if __name__ == "__main__":
    unittest.main()
