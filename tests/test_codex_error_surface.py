"""Tests for surfacing Codex chat turn failure reasons from JSON event streams."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["AESOP_SIMULATED_ROUTE"] = "1"
os.environ["AESOP_PROBE_OFFLINE"] = "1"

from aesop_studio import providers  # noqa: E402
from aesop_studio.services import Services  # noqa: E402
from aesop_studio.store import Store  # noqa: E402
from aesop_studio.tasks import Supervisor, TERMINAL  # noqa: E402

RECORDED_TOP_LEVEL_ERROR = (
    '{"type":"error","message":"You\'ve hit your usage limit. Visit '
    'https://chatgpt.com/settings/usage to purchase more credits or try again at 8:36 PM."}'
)
RECORDED_TURN_FAILED = (
    '{"type":"turn.failed","error":{"message":"You\'ve hit your usage limit. Visit '
    'https://chatgpt.com/settings/usage to purchase more credits or try again at 8:36 PM."}}'
)
RECORDED_ITEM_WARNING = (
    '{"type":"item.completed","item":{"type":"error","message":"Codex is ignoring 1 '
    'unrecognized configuration setting..."}}'
)


def _wait_terminal(sup: Supervisor, tid: str, timeout: float = 30.0):
    end = time.time() + timeout
    while time.time() < end:
        t = sup.get(tid)
        if t and t["state"] in TERMINAL:
            return t
        time.sleep(0.05)
    raise AssertionError(f"task {tid} stuck in {sup.get(tid)['state'] if sup.get(tid) else 'unknown'}")


class TestCodexErrorSurface(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-codex-test-"))
        self.root = self.tmp / "proj"
        self.root.mkdir()
        self.store = Store(self.tmp / "data")
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        providers.refresh(self.store)
        self.p = self.svc.create_project("Demo", str(self.root), "simulated")
        self.store.x("INSERT INTO kv(k,v) VALUES(?, 'on')", (f"agent_ack:{self.p['id']}",))
        routes = providers.cached(self.store)
        routes["codex"] = {
            "id": "codex", "provider": "openai", "route_type": "official_cli",
            "state": "READY_INCLUDED", "supported_modes": ["chat", "agent"],
            "billing_basis": "subscription_included", "executable": "codex.exe",
        }
        self.store.x("INSERT INTO kv(k,v) VALUES('routes',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                     (json.dumps(routes),))

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_with_codex_output(self, output_lines: list[str], exit_code: int = 1, mode: str = "agent") -> dict:
        script_file = self.tmp / f"fake_codex_{time.time_ns()}.py"
        script_content = (
            "import sys\n"
            f"lines = {output_lines!r}\n"
            "for line in lines:\n"
            "    sys.stdout.write(line + '\\n')\n"
            "sys.stdout.flush()\n"
            f"sys.exit({exit_code})\n"
        )
        script_file.write_text(script_content, encoding="utf-8")
        with patch("aesop_studio.providers.build_argv", return_value=[sys.executable, str(script_file)]):
            tid = self.sup.create(self.p, "codex", "test prompt", mode=mode)
            return _wait_terminal(self.sup, tid)

    def test_codex_turn_failed_and_error_both_present(self):
        t = self._run_with_codex_output([RECORDED_TOP_LEVEL_ERROR, RECORDED_TURN_FAILED])
        self.assertEqual(t["state"], "FAILED")
        expected = (
            "exit code 1: You've hit your usage limit. Visit https://chatgpt.com/settings/usage "
            "to purchase more credits or try again at 8:36 PM."
        )
        self.assertEqual(t["error"], expected)

    def test_codex_only_top_level_error(self):
        t = self._run_with_codex_output([RECORDED_TOP_LEVEL_ERROR])
        self.assertEqual(t["state"], "FAILED")
        expected = (
            "exit code 1: You've hit your usage limit. Visit https://chatgpt.com/settings/usage "
            "to purchase more credits or try again at 8:36 PM."
        )
        self.assertEqual(t["error"], expected)

    def test_codex_item_completed_warning_ignored(self):
        t = self._run_with_codex_output([RECORDED_ITEM_WARNING])
        self.assertEqual(t["state"], "FAILED")
        self.assertEqual(t["error"], "exit code 1")

    def test_codex_item_warning_with_turn_failed(self):
        t = self._run_with_codex_output([RECORDED_ITEM_WARNING, RECORDED_TURN_FAILED])
        self.assertEqual(t["state"], "FAILED")
        expected = (
            "exit code 1: You've hit your usage limit. Visit https://chatgpt.com/settings/usage "
            "to purchase more credits or try again at 8:36 PM."
        )
        self.assertEqual(t["error"], expected)

    def test_codex_multiple_turn_failed_picks_last(self):
        lines = [
            '{"type":"turn.failed","error":{"message":"First turn error"}}',
            '{"type":"turn.failed","error":{"message":"Second turn error"}}',
        ]
        t = self._run_with_codex_output(lines)
        self.assertEqual(t["state"], "FAILED")
        self.assertEqual(t["error"], "exit code 1: Second turn error")

    def test_codex_error_message_capped_at_300(self):
        long_msg = "X" * 400
        line = json.dumps({"type": "turn.failed", "error": {"message": long_msg}})
        t = self._run_with_codex_output([line])
        self.assertEqual(t["state"], "FAILED")
        self.assertEqual(t["error"], f"exit code 1: {'X' * 300}")

    def test_codex_error_message_redacted(self):
        secret_line = '{"type":"turn.failed","error":{"message":"Error using sk-proj-0123456789abcdef01234"}}'
        t = self._run_with_codex_output([secret_line])
        self.assertEqual(t["state"], "FAILED")
        self.assertEqual(t["error"], "exit code 1: Error using [REDACTED]")

    def test_codex_direct_helper_if_present(self):
        from aesop_studio import tasks
        if hasattr(tasks, "_codex_err"):
            log_file = self.tmp / "test.log"
            log_file.write_text(RECORDED_TOP_LEVEL_ERROR + "\n" + RECORDED_TURN_FAILED + "\n", encoding="utf-8")
            msg = tasks._codex_err(str(log_file))
            self.assertEqual(
                msg,
                "You've hit your usage limit. Visit https://chatgpt.com/settings/usage "
                "to purchase more credits or try again at 8:36 PM."
            )
