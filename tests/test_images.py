"""Photos in chat: detection by content, per-message limits, provider gating, and delivery to each route type."""
import base64
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

os.environ["AESOP_SIMULATED_ROUTE"] = "1"
os.environ["AESOP_PROBE_OFFLINE"] = "1"

from aesop_studio import providers, security  # noqa: E402
from aesop_studio.services import MAX_IMAGES_PER_MESSAGE, Services  # noqa: E402
from aesop_studio.store import Store  # noqa: E402
from aesop_studio.tasks import TERMINAL, Supervisor, _data_urls  # noqa: E402

# 1x1 PNG and a tiny JPEG header with a SOF0 marker (2x3)
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xc0\x00\x11\x08\x00\x03\x00\x02" + b"\x00" * 40


class TestImages(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-img-"))
        (self.tmp / "p").mkdir()
        self.store = Store(self.tmp / "d")
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        providers.refresh(self.store)
        self.p = self.svc.create_project("P", str(self.tmp / "p"), "simulated")
        self.svc.update_project(self.p["id"], {"transfer_policy": {"simulated": True}})
        self.c = self.svc.new_conversation(self.p["id"])

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_images_detected_by_content_not_name(self):
        self.assertEqual(security.image_kind(PNG), "png")
        self.assertEqual(security.image_size(PNG), (1, 1))
        self.assertEqual(security.image_size(JPEG), (2, 3))
        a = self.svc.attach(self.p["id"], "screenshot.png", PNG)
        self.assertEqual(a["extract_status"], "image")
        b = self.svc.attach(self.p["id"], "notes.png", b"just text pretending")
        self.assertNotEqual(b["extract_status"], "image")
        renamed = self.svc.attach(self.p["id"], "photo.txt", JPEG)
        self.assertEqual(renamed["extract_status"], "image")
        path, mime = self.svc.image_file(a["id"])
        self.assertEqual(mime, "image/png")
        self.assertEqual(path.read_bytes(), PNG)
        with self.assertRaises(KeyError):
            self.svc.image_file(b["id"])

    def test_photo_reaches_cli_route_and_stays_out_of_text_context(self):
        a = self.svc.attach(self.p["id"], "screen.png", PNG)
        ctx = self.svc.build_context(self.p["id"], self.c["id"], "what is this?", [a["id"]], "simulated")
        self.assertIn("1 photo attached by the user: screen.png", ctx)
        self.assertNotIn("<file", ctx)
        r = self.svc.send(self.p["id"], self.c["id"], "what is this?", [a["id"]], None)
        end = time.time() + 20
        while self.sup.get(r["task_id"])["state"] not in TERMINAL and time.time() < end:
            time.sleep(0.05)
        t = self.sup.get(r["task_id"])
        self.assertEqual(t["state"], "COMPLETED", t["error"])
        self.assertIn("photos=1", self.sup.output(t["id"])[0])  # staged into the task's own folder
        self.assertFalse(Path(t["cwd"]).exists())  # and removed with it

    def test_deleting_conversation_removes_its_photos(self):
        from aesop_studio import deletion
        a = self.svc.attach(self.p["id"], "screen.png", PNG)
        keep = self.svc.attach(self.p["id"], "kept.png", PNG + b"k")  # never sent: stays in project files
        r = self.svc.send(self.p["id"], self.c["id"], "look", [a["id"]], None)
        end = time.time() + 20
        while self.sup.get(r["task_id"])["state"] not in TERMINAL and time.time() < end:
            time.sleep(0.05)
        path = self.store.data_dir / self.store.one("SELECT stored_path FROM attachments WHERE id=?", (a["id"],))["stored_path"]
        out = deletion.delete_conversation(self.store, self.svc, self.p["id"], self.c["id"])
        self.assertEqual(out["photos_deleted"], 1)
        self.assertIsNone(self.store.one("SELECT id FROM attachments WHERE id=?", (a["id"],)))
        self.assertFalse(path.exists())
        self.assertIsNotNone(self.store.one("SELECT id FROM attachments WHERE id=?", (keep["id"],)))

    def test_limits_and_provider_gating(self):
        ids = [self.svc.attach(self.p["id"], f"p{i}.png", PNG + bytes([i]))["id"] for i in range(MAX_IMAGES_PER_MESSAGE + 1)]
        with self.assertRaises(ValueError):
            self.svc.build_context(self.p["id"], self.c["id"], "x", ids, "simulated")
        self.svc.build_context(self.p["id"], self.c["id"], "x", ids[:MAX_IMAGES_PER_MESSAGE], "simulated")
        with self.assertRaises(ValueError) as e:  # research routes answer from the web: no files, no photos
            self.svc.build_context(self.p["id"], self.c["id"], "x", ids[:1], "perplexity")
        self.assertIn("not files or photos", str(e.exception))
        self.svc.update_project(self.p["id"], {"transfer_policy": {"simulated": True, "grok": True, "copilot": True,
                                                                   "cursor": True, "antigravity": True, "zai": True}})
        for rid in ("grok", "copilot", "cursor", "antigravity", "zai"):  # every in-app CLI route now takes photos
            ctx = self.svc.build_context(self.p["id"], self.c["id"], "x", ids[:1], rid)
            self.assertIn("1 photo attached", ctx)
        self.svc.update_project(self.p["id"], {"transfer_policy": {"simulated": False}})
        with self.assertRaises(PermissionError):
            self.svc.build_context(self.p["id"], self.c["id"], "x", ids[:1], "simulated")

    def test_argv_hands_photos_to_codex_and_claude(self):
        if providers._codex_cmd():
            argv = providers.build_argv("codex", "chat", "C:/t", "C:/t/o.txt", images=["images/photo1.png"])
            i = argv.index("-i")
            self.assertTrue(argv[i + 1].endswith("photo1.png"))
            self.assertLess(i, argv.index("--skip-git-repo-check"))  # before other flags: never swallowed
            self.assertEqual(argv[-1], "-")
        if providers._claude_cmd():
            plain = providers.build_argv("claude", "chat", "C:/t", "C:/t/o.txt")
            self.assertEqual(plain[plain.index("--tools") + 1], "")
            withimg = providers.build_argv("claude", "chat", "C:/t", "C:/t/o.txt", images=["images/photo1.png"])
            self.assertEqual(withimg[withimg.index("--tools") + 1], "Read")

    def test_argv_hands_photos_to_every_cli_route(self):
        from unittest.mock import patch
        with patch.object(providers, "_copilot_cmd", return_value=["copilot"]):
            a = providers.build_argv("copilot", "chat", "C:/t", "C:/t/o.txt", images=["images/photo1.png"])
            self.assertTrue(a[a.index("--attachment") + 1].endswith("photo1.png"))
            self.assertNotIn("--attachment", providers.build_argv("copilot", "chat", "C:/t", "C:/t/o.txt"))
        with patch.object(providers, "_grok_cmd", return_value=["grok"]):
            a = providers.build_argv("grok", "chat", "C:/t", "C:/t/o.txt", prompt="p", images=["images/photo1.png"])
            self.assertEqual(a[a.index("--tools") + 1], "read_file")  # photos need the file reader, nothing else
            plain = providers.build_argv("grok", "chat", "C:/t", "C:/t/o.txt", prompt="p")
            self.assertEqual(plain[plain.index("--tools") + 1], "")
        from aesop_studio.tasks import READ_TOOL_IMAGE_ROUTES
        for rid in ("claude", "zai", "cursor", "antigravity", "grok"):  # staged copies + a prompt line to open them
            self.assertIn(rid, READ_TOOL_IMAGE_ROUTES)

    def test_reference_dirs_reach_every_cli_as_add_dir(self):
        from unittest.mock import patch
        ref = str(self.tmp / "p")
        cases = (("codex", "agent", "_codex_cmd"), ("claude", "agent", "_claude_cmd"), ("zai", "agent", "_zai_cmd"),
                 ("cursor", "agent", "_cursor_cmd"), ("cursor", "chat", "_cursor_cmd"),
                 ("copilot", "chat", "_copilot_cmd"), ("antigravity", "chat", "_agy_cmd"))
        for rid, mode, fn in cases:
            with self.subTest(route=rid), patch.object(providers, fn, return_value=[rid]):
                a = providers.build_argv(rid, mode, "C:/t", "C:/t/o.txt", prompt="p", extra_dirs=[ref])
                self.assertEqual(a[a.index("--add-dir") + 1], ref)
                if rid == "antigravity":  # the argv prompt stays last so --add-dir can never swallow it
                    self.assertTrue(a[-1].startswith("-p="))
                if rid == "codex":
                    self.assertEqual(a[-1], "-")
                self.assertNotIn("--add-dir", providers.build_argv(rid, mode, "C:/t", "C:/t/o.txt", prompt="p"))
        with patch.object(providers, "_grok_cmd", return_value=["grok"]):  # grok.exe rejects additional directories
            a = providers.build_argv("grok", "agent", "C:/t", "C:/t/o.txt", prompt="p", extra_dirs=[ref])
            self.assertNotIn("--add-dir", a)

    def test_reference_dirs_validated_and_in_work_preview_only(self):
        ref = self.tmp / "ref"
        ref.mkdir()
        p = self.svc.update_project(self.p["id"], {"reference_dirs": f"{ref}\n\n{ref}\n{self.tmp / 'p'}"})
        self.assertEqual(p["reference_dirs"], [str(ref.resolve())])  # de-duplicated; the project root is implied
        for bad in (str(Path.home()), str(Path.home() / ".ssh"), "relative/dir", str(self.tmp / "missing")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.svc.update_project(self.p["id"], {"reference_dirs": [bad]})
        self.assertEqual(self.svc.project(self.p["id"])["reference_dirs"], [str(ref.resolve())])  # refusals change nothing
        note = self.svc.reference_note(self.svc.project(self.p["id"]))
        self.assertIn(str(ref.resolve()), note)
        self.assertIn("read-only", note)
        chat_ctx = self.svc.build_context(self.p["id"], self.c["id"], "x", [], "simulated")
        self.assertNotIn("Reference folders", chat_ctx)  # chat runs in a sandbox with no file tools: no false promise
        mem = self.store.q("SELECT content FROM memory WHERE project_id=? AND kind='permission'", (self.p["id"],))
        self.assertTrue(any("Reference folders" in m["content"] for m in mem))

    def test_data_urls_for_metered_route(self):
        f = self.tmp / "x.jpg"
        f.write_bytes(JPEG)
        self.assertTrue(_data_urls([str(f)])[0].startswith("data:image/jpeg;base64,"))


if __name__ == "__main__":
    unittest.main()
