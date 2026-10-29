"""PR #6 Tier A (A1): retirement admission gate and drain."""

import os
import threading
import unittest
from types import SimpleNamespace

os.environ["AESOP_SIMULATED_ROUTE"] = "1"
os.environ["AESOP_PROBE_OFFLINE"] = "1"

from aesop_studio.server import (  # noqa: E402
    WORK_START_HANDLERS,
    Handler,
    run_source_retire_watcher,
)


class TestRetirementAdmissionRepro(unittest.TestCase):
    def test_a1_retiring_rejects_task_start_like_repro(self):
        calls = []
        sessions = SimpleNamespace(key_ok=lambda *_: True)
        handler = SimpleNamespace(
            app=SimpleNamespace(
                retiring=True,
                sessions=sessions,
                allowed_hosts=lambda: {"127.0.0.1:8766"},
                _retire_lock=threading.Lock(),
                _in_flight=0,
            ),
            path="/api/projects/synthetic/tasks",
            headers={
                "Origin": "http://127.0.0.1:8766",
                "X-CSRF-Token": "synthetic",
                "X-Aesop-Key": "synthetic",
            },
            _sitem={"csrf": "synthetic"},
            _host_ok=lambda: True,
            _session=lambda: "synthetic-session",
            task_new=lambda *_: calls.append("task_new"),
            err=lambda code, message: calls.append(("error", code, message)),
            _admit_work_start=lambda: Handler._admit_work_start(handler),
            _release_work_start=lambda: Handler._release_work_start(handler),
        )
        Handler._dispatch(handler, "POST")
        self.assertNotIn("task_new", calls)
        self.assertTrue(
            any(c[0] == "error" and c[1] == 503 for c in calls if isinstance(c, tuple))
        )

    def test_a1_work_start_handler_table_covers_task_new(self):
        self.assertIn("task_new", WORK_START_HANDLERS)
        self.assertIn("send", WORK_START_HANDLERS)
        self.assertNotIn("project_file_put", WORK_START_HANDLERS)

    def test_a1_editor_save_allowed_while_retiring(self):
        calls = []
        sessions = SimpleNamespace(key_ok=lambda *_: True)
        handler = SimpleNamespace(
            app=SimpleNamespace(
                retiring=True,
                sessions=sessions,
                allowed_hosts=lambda: {"127.0.0.1:8766"},
                _retire_lock=threading.Lock(),
                _in_flight=0,
            ),
            path="/api/projects/synthetic/file",
            headers={
                "Origin": "http://127.0.0.1:8766",
                "X-CSRF-Token": "synthetic",
                "X-Aesop-Key": "synthetic",
            },
            _sitem={"csrf": "synthetic"},
            _host_ok=lambda: True,
            _session=lambda: "synthetic-session",
            project_file_put=lambda *_: calls.append("saved"),
            err=lambda code, message: calls.append(("error", code, message)),
            _admit_work_start=lambda: Handler._admit_work_start(handler),
            _release_work_start=lambda: Handler._release_work_start(handler),
        )
        Handler._dispatch(handler, "POST")
        self.assertEqual(calls, ["saved"])

    def test_a1_watcher_waits_for_in_flight_before_shutdown(self):
        app = SimpleNamespace(
            retiring=False,
            source_mtime=0.0,
            _retire_lock=threading.Lock(),
            _in_flight=1,
            browser=SimpleNamespace(stop=lambda: None),
        )
        shutdowns = []
        sleeps = []

        def sleep_fn(secs):
            sleeps.append(secs)
            if len(sleeps) == 1:
                with app._retire_lock:
                    app._in_flight = 0

        run_source_retire_watcher(
            app,
            SimpleNamespace(shutdown=lambda: shutdowns.append(True)),
            source_mtime_fn=lambda: 1.0,
            sleep_fn=sleep_fn,
            has_live_work_fn=lambda: False,
            stop_browser_fn=lambda: None,
            shutdown_fn=lambda: shutdowns.append(True),
        )
        self.assertTrue(app.retiring)
        self.assertEqual(shutdowns, [True])


if __name__ == "__main__":
    unittest.main()
