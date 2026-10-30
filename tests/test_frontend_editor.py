"""Editor save guard and follow-up inspector navigation (source + in-memory harness)."""

import shutil
import subprocess
import unittest
from pathlib import Path

APP_JS = Path(__file__).resolve().parent.parent / "static" / "app.js"
HARNESS = Path(__file__).resolve().parent / "app_editor_harness.mjs"


class TestFrontendEditor(unittest.TestCase):
    def test_insp_editor_save_waits_for_load(self):
        chunk = APP_JS.read_text(encoding="utf-8")
        start = chunk.index("async function inspEditor")
        body = chunk[start : start + 3200]
        self.assertIn("let loaded = false", body)
        self.assertIn("if (!current || !loaded || ta.disabled) return", body)
        self.assertIn("loaded = false", body)
        self.assertIn("syncSave", body)

    def test_save_before_load_submits_nothing(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        r = subprocess.run(
            [node, str(HARNESS)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(r.returncode, 0, r.stderr or r.stdout)

    def test_a2_editor_compose_work_mode(self):
        chunk = APP_JS.read_text(encoding="utf-8")
        self.assertIn('else { workOn = false; ssSet(workKey, ""); }', chunk)

    def test_a3_editor_save_baseline_before_await(self):
        chunk = APP_JS.read_text(encoding="utf-8")
        self.assertIn("const path = current, sent = ta.value", chunk)
        self.assertIn("if (current === path) original = sent", chunk)

    def test_a4_editor_dirty_guards(self):
        chunk = APP_JS.read_text(encoding="utf-8")
        self.assertIn("function editorDirty()", chunk)
        self.assertIn("function confirmDiscardEditors()", chunk)
        self.assertIn("syncEditorBeforeUnload", chunk)
        self.assertIn(
            "function openGlobal(which) {\n  if (!confirmDiscardEditors()) return Promise.resolve();",
            chunk,
        )

    def test_a5_draft_replace_confirm(self):
        chunk = APP_JS.read_text(encoding="utf-8")
        self.assertIn(
            "Replace your unsent chat draft with text from the editor?", chunk
        )

    def test_harness_a2_through_a5(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        r = subprocess.run(
            [node, str(HARNESS)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(r.returncode, 0, r.stderr or r.stdout)

    def test_open_fix_task_uses_open_inspector(self):
        chunk = APP_JS.read_text(encoding="utf-8")
        self.assertIn(
            'const openFixTask = (id) => { S.taskSel = id; openInspector("changes"); };',
            chunk,
        )


if __name__ == "__main__":
    unittest.main()
