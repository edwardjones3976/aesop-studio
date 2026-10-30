"""PR #6 Tier A (A1): retirement admission gate and drain."""

import os
import threading
import time
import unittest
from types import SimpleNamespace

os.environ["AESOP_SIMULATED_ROUTE"] = "1"
os.environ["AESOP_PROBE_OFFLINE"] = "1"

from aesop_studio.server import (  # noqa: E402
    RETIRING_ADMIT_EXEMPT,
    ROUTES,
    WORK_START_HANDLERS,
    Handler,
    mutating_route_handlers,
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
            _admit_mutating=lambda name: Handler._admit_mutating(handler, name),
            _release_mutating=lambda: Handler._release_mutating(handler),
        )
        Handler._dispatch(handler, "POST")
        self.assertNotIn("task_new", calls)
        self.assertTrue(
            any(c[0] == "error" and c[1] == 503 for c in calls if isinstance(c, tuple))
        )

    def test_a1_mutating_routes_accounted(self):
        mutating = mutating_route_handlers()
        self.assertIn("project_file_put", mutating)
        self.assertIn("project_file_put", RETIRING_ADMIT_EXEMPT)
        self.assertFalse(WORK_START_HANDLERS & RETIRING_ADMIT_EXEMPT)
        self.assertTrue(WORK_START_HANDLERS.issubset(mutating))
        for method, _pat, name in ROUTES:
            if method in ("POST", "PATCH"):
                self.assertIn(name, mutating)

    def test_a1_work_start_handler_table_covers_task_new(self):
        self.assertIn("task_new", WORK_START_HANDLERS)
        self.assertIn("send", WORK_START_HANDLERS)
        self.assertNotIn("project_file_put", WORK_START_HANDLERS)
        self.assertIn("project_file_put", RETIRING_ADMIT_EXEMPT)

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
            _admit_mutating=lambda name: Handler._admit_mutating(handler, name),
            _release_mutating=lambda: Handler._release_mutating(handler),
        )
        Handler._dispatch(handler, "POST")
        self.assertEqual(calls, ["saved"])
        self.assertEqual(handler.app._in_flight, 0)

    def test_a1_editor_save_increments_in_flight_until_done(self):
        app = SimpleNamespace(
            retiring=False,
            sessions=SimpleNamespace(key_ok=lambda *_: True),
            allowed_hosts=lambda: {"127.0.0.1:8766"},
            _retire_lock=threading.Lock(),
            _in_flight=0,
        )
        entered = threading.Event()
        release = threading.Event()

        def project_file_put(*_a):
            entered.set()
            release.wait(timeout=2)
            return None

        handler = SimpleNamespace(
            app=app,
            path="/api/projects/synthetic/file",
            headers={
                "Origin": "http://127.0.0.1:8766",
                "X-CSRF-Token": "synthetic",
                "X-Aesop-Key": "synthetic",
            },
            _sitem={"csrf": "synthetic"},
            _host_ok=lambda: True,
            _session=lambda: "synthetic-session",
            project_file_put=project_file_put,
            err=lambda code, message: ("error", code, message),
            _admit_mutating=lambda name: Handler._admit_mutating(handler, name),
            _release_mutating=lambda: Handler._release_mutating(handler),
        )

        def run_save():
            Handler._dispatch(handler, "POST")

        t = threading.Thread(target=run_save, daemon=True)
        t.start()
        self.assertTrue(entered.wait(timeout=2))
        self.assertEqual(app._in_flight, 1)
        release.set()
        t.join(timeout=2)
        self.assertEqual(app._in_flight, 0)

    def test_a1_concurrent_retire_denies_new_work_start(self):
        app = SimpleNamespace(
            retiring=False,
            sessions=SimpleNamespace(key_ok=lambda *_: True),
            allowed_hosts=lambda: {"127.0.0.1:8766"},
            _retire_lock=threading.Lock(),
            _in_flight=0,
        )
        hold = threading.Event()
        release = threading.Event()
        results = []

        def task_new(*_a):
            hold.set()
            release.wait(timeout=2)
            results.append("task_new")

        handler = SimpleNamespace(
            app=app,
            path="/api/projects/synthetic/tasks",
            headers={
                "Origin": "http://127.0.0.1:8766",
                "X-CSRF-Token": "synthetic",
                "X-Aesop-Key": "synthetic",
            },
            _sitem={"csrf": "synthetic"},
            _host_ok=lambda: True,
            _session=lambda: "synthetic-session",
            task_new=task_new,
            err=lambda code, message: results.append(("error", code, message)),
            _admit_mutating=lambda name: Handler._admit_mutating(handler, name),
            _release_mutating=lambda: Handler._release_mutating(handler),
        )

        def first():
            Handler._dispatch(handler, "POST")

        t = threading.Thread(target=first, daemon=True)
        t.start()
        self.assertTrue(hold.wait(timeout=2))
        with app._retire_lock:
            app.retiring = True
        Handler._dispatch(handler, "POST")
        self.assertNotIn("task_new", results[1:])
        self.assertTrue(any(r[1] == 503 for r in results if isinstance(r, tuple)))
        release.set()
        t.join(timeout=2)

    def test_a1_watcher_waits_for_in_flight_before_shutdown(self):
        app = SimpleNamespace(
            retiring=False,
            source_mtime=0.0,
            sessions=SimpleNamespace(key_ok=lambda *_: True),
            allowed_hosts=lambda: {"127.0.0.1:8766"},
            _retire_lock=threading.Lock(),
            _in_flight=0,
            browser=SimpleNamespace(stop=lambda: None),
        )
        shutdowns = []
        hold = threading.Event()
        release = threading.Event()

        def slow_mutating(*_a):
            hold.set()
            release.wait(timeout=2)

        handler = SimpleNamespace(
            app=app,
            path="/api/projects/synthetic/file",
            headers={
                "Origin": "http://127.0.0.1:8766",
                "X-CSRF-Token": "synthetic",
                "X-Aesop-Key": "synthetic",
            },
            _sitem={"csrf": "synthetic"},
            _host_ok=lambda: True,
            _session=lambda: "synthetic-session",
            project_file_put=slow_mutating,
            err=lambda *_: None,
            _admit_mutating=lambda name: Handler._admit_mutating(handler, name),
            _release_mutating=lambda: Handler._release_mutating(handler),
        )

        def in_flight_request():
            Handler._dispatch(handler, "POST")

        t = threading.Thread(target=in_flight_request, daemon=True)
        t.start()
        self.assertTrue(hold.wait(timeout=2))

        watcher = threading.Thread(
            target=lambda: run_source_retire_watcher(
                app,
                SimpleNamespace(shutdown=lambda: shutdowns.append(True)),
                source_mtime_fn=lambda: 1.0,
                sleep_fn=lambda secs: time.sleep(0.01 if secs < 2 else 0.02),
                has_live_work_fn=lambda: False,
                stop_browser_fn=lambda: None,
                shutdown_fn=lambda: shutdowns.append(True),
            ),
            daemon=True,
        )
        watcher.start()
        watcher.join(timeout=2)
        self.assertEqual(shutdowns, [])
        release.set()
        t.join(timeout=2)
        watcher.join(timeout=2)
        self.assertTrue(app.retiring)
        self.assertEqual(shutdowns, [True])


if __name__ == "__main__":
    unittest.main()
