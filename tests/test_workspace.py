"""In-app editor: project-folder tree and text read/write stay inside one project's root."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ["AESOP_SIMULATED_ROUTE"] = "1"
os.environ["AESOP_PROBE_OFFLINE"] = "1"

from aesop_studio.security import ScopeError  # noqa: E402
from aesop_studio.services import Services  # noqa: E402
from aesop_studio.store import Store  # noqa: E402
from aesop_studio.tasks import Supervisor  # noqa: E402
from aesop_studio import providers, workspace  # noqa: E402


class TestWorkspace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-ws-"))
        self.root = self.tmp / "proj"
        self.root.mkdir()
        (self.root / "readme.md").write_text("# hello\n", encoding="utf-8")
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "pkg.js").write_text("secret-dep\n", encoding="utf-8")
        (self.root / ".env").write_text("TOKEN=nope\n", encoding="utf-8")
        self.store = Store(self.tmp / "data")
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        providers.refresh(self.store)
        self.p = self.svc.create_project("Demo", str(self.root), "simulated")
        self.other = self.tmp / "other"
        self.other.mkdir()
        self.q = self.svc.create_project("Other", str(self.other), "simulated")
        (self.other / "foreign.txt").write_text("not yours\n", encoding="utf-8")

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tree_is_this_project_only(self):
        tree = workspace.list_tree(self.p)
        paths = {e["path"] for e in tree["entries"]}
        self.assertIn("readme.md", paths)
        self.assertIn("src", paths)
        self.assertIn("src/app.py", paths)
        self.assertNotIn("node_modules", paths)
        self.assertFalse(any(p.startswith("node_modules") for p in paths))
        self.assertNotIn(".env", paths)
        self.assertNotIn("foreign.txt", paths)
        other = workspace.list_tree(self.q)
        self.assertEqual({e["path"] for e in other["entries"]}, {"foreign.txt"})

    def test_read_and_write_stay_in_project(self):
        got = workspace.read_file(self.p, "src/app.py")
        self.assertIn("print", got["content"])
        with self.assertRaises(PermissionError):
            workspace.write_file(self.store, self.p, "src/app.py", "print('no')\n")
        self.store.x("INSERT INTO kv(k,v) VALUES(?, 'on')", (f"agent_ack:{self.p['id']}",))
        saved = workspace.write_file(self.store, self.p, "src/app.py", "print('yes')\n")
        self.assertTrue(saved["saved"])
        self.assertEqual((self.root / "src" / "app.py").read_text(encoding="utf-8"), "print('yes')\n")
        with self.assertRaises(ScopeError):
            workspace.read_file(self.p, "../other/foreign.txt")
        with self.assertRaises(ScopeError):
            workspace.write_file(self.store, self.p, "../other/foreign.txt", "x")
        with self.assertRaises(ScopeError):
            workspace.read_file(self.p, ".env")
        self.assertEqual((self.other / "foreign.txt").read_text(encoding="utf-8"), "not yours\n")

    def test_read_keeps_owner_file_text(self):
        (self.root / "cfg.py").write_text("token = 'sk-" + ("a" * 20) + "'\n", encoding="utf-8")
        got = workspace.read_file(self.p, "cfg.py")
        self.assertIn("sk-", got["content"])
        self.assertNotIn("[REDACTED]", got["content"])

    def test_new_file_in_existing_folder(self):
        self.store.x("INSERT INTO kv(k,v) VALUES(?, 'on')", (f"agent_ack:{self.p['id']}",))
        workspace.write_file(self.store, self.p, "notes.md", "practice\n")
        self.assertEqual((self.root / "notes.md").read_text(encoding="utf-8"), "practice\n")
