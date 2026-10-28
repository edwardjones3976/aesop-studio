"""Store migration idempotence and argv_meta path masking (WO-20261028-002 rev3)."""

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ["AESOP_SIMULATED_ROUTE"] = "1"
os.environ["AESOP_PROBE_OFFLINE"] = "1"

from aesop_studio import providers  # noqa: E402
from aesop_studio.services import Services  # noqa: E402
from aesop_studio.store import Store, new_id  # noqa: E402
from aesop_studio.tasks import Supervisor, _argv_meta_args  # noqa: E402


class TestStoreMigrationIdempotent(unittest.TestCase):
    def test_opening_store_twice_on_same_data_dir(self):
        d = Path(tempfile.mkdtemp(prefix="aesop-mig-"))
        try:
            s1 = Store(d / "data")
            s1.x("INSERT INTO kv(k,v) VALUES('migration_probe','1')")
            with s1.conn() as c:
                projects_cols = {r[1] for r in c.execute("PRAGMA table_info(projects)")}
                ledger_cols = {r[1] for r in c.execute("PRAGMA table_info(ledger)")}
            s1.close()
            s2 = Store(d / "data")
            with s2.conn() as c:
                self.assertEqual(
                    projects_cols,
                    {r[1] for r in c.execute("PRAGMA table_info(projects)")},
                )
                self.assertIn("reference_dirs", projects_cols)
                self.assertIn("purpose", ledger_cols)
            self.assertEqual(
                s2.one("SELECT v FROM kv WHERE k='migration_probe'")["v"], "1"
            )
            s2.close()
            Store(d / "data").close()
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestArgvMetaMasking(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-argv-"))
        self.root = self.tmp / "proj"
        self.root.mkdir()
        self.store = Store(self.tmp / "data")
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        providers.refresh(self.store)
        self.p = self.svc.create_project("Demo", str(self.root), "simulated")

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_argv_meta_masks_add_dir_and_attachment_values(self):
        tid = new_id("task")
        chat_dir = self.tmp / "chat"
        chat_dir.mkdir()
        out_path = str(self.store.data_dir / "task-output" / f"{tid}.log")
        Path(out_path + ".last.txt").write_text("done", encoding="utf-8")
        self.store.x(
            "INSERT INTO tasks(id,project_id,provider,prompt,state,cwd,output_path,created,checkpoint,reservation_usd) "
            "VALUES(?,?,?,?,?,?,?,?,?,0)",
            (
                tid,
                self.p["id"],
                "codex",
                "hi",
                "CREATED",
                str(chat_dir),
                out_path,
                time.time(),
                "{}",
            ),
        )
        secret_dir = str(self.tmp / "owner-only-ref")
        Path(secret_dir).mkdir()
        secret_file = str(self.tmp / "owner-only.png")
        Path(secret_file).write_bytes(b"\x89PNG")
        argv = [
            "codex",
            "--add-dir",
            secret_dir,
            "--attachment",
            secret_file,
            "-p=hi",
        ]
        proc = mock.MagicMock()
        proc.pid = 4242
        proc.stdout.read1 = lambda _n: b""
        proc.wait.return_value = 0
        proc.returncode = 0
        with (
            mock.patch.object(providers, "build_argv", return_value=argv),
            mock.patch("subprocess.Popen", return_value=proc),
            mock.patch("aesop_studio.winjob.contain", return_value=object()),
            mock.patch("aesop_studio.winjob.terminate", return_value=True),
            mock.patch("aesop_studio.winjob.close"),
        ):
            self.sup._run(
                tid,
                "codex",
                "chat",
                str(chat_dir),
                "hi",
                out_path,
                30,
                None,
                None,
            )
        meta = json.loads(self.sup.get(tid)["argv_meta"])
        joined = " ".join(meta["args"])
        self.assertIn("<path>", meta["args"])
        self.assertNotIn(secret_dir, joined)
        self.assertNotIn(secret_file, joined)
        self.assertIn("-p=<prompt>", meta["args"])

    def test_argv_meta_masks_zcode_and_gemini_values(self):
        chat = str(self.tmp / "chat")
        Path(chat).mkdir()
        zctx = "zcode-secret-context"
        gdir = str(self.tmp / "ref-only")
        Path(gdir).mkdir()
        zargs = _argv_meta_args(["zcode.cjs", "-p", zctx], chat)
        self.assertEqual(zargs, ["-p", "<prompt>"])
        self.assertNotIn(zctx, " ".join(zargs))
        gargv = [
            "gemini.js",
            "--include-directories",
            gdir,
            "-p",
            "Respond to the latest user message in the input above.",
        ]
        gargs = _argv_meta_args(gargv, chat)
        self.assertIn("<path>", gargs)
        self.assertNotIn(gdir, " ".join(gargs))
        long_prompt = "x" * 201
        self.assertIn("<prompt>", _argv_meta_args(["grok", "-p", long_prompt], chat))


if __name__ == "__main__":
    unittest.main()
