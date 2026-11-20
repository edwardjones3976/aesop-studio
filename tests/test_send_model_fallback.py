"""Send-time per-model quota fallback for multi-model CLI routes (Antigravity first).

Extends WO-20261027-002 beyond verify_live into Supervisor._run / Services.send.
"""
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
from aesop_studio.tasks import TERMINAL, Supervisor  # noqa: E402

ARGON = "gemini-4-argon-high"
FLASH = "gemini-3.8-flash-low"
QUOTA = "RESOURCE_EXHAUSTED 429 Individual quota reached. Resets in 81h"


def _wait_terminal(sup: Supervisor, tid: str, timeout: float = 30.0):
    end = time.time() + timeout
    while time.time() < end:
        t = sup.get(tid)
        if t and t["state"] in TERMINAL:
            return t
        time.sleep(0.05)
    raise AssertionError(
        f"task {tid} stuck in {sup.get(tid)['state'] if sup.get(tid) else 'unknown'}"
    )


class SendModelFallback(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-send-fallback-"))
        self.root = self.tmp / "proj"
        self.root.mkdir()
        self.store = Store(self.tmp / "data")
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        providers.refresh(self.store)
        self.p = self.svc.create_project("Demo", str(self.root), "simulated")
        routes = providers.cached(self.store)
        routes["antigravity"] = {
            "id": "antigravity", "provider": "google", "route_type": "official_cli",
            "state": "READY_INCLUDED", "supported_modes": ["chat"],
            "billing_basis": "subscription_included", "executable": "agy",
            "installed": True, "verifiable": True,
        }
        self.store.x("INSERT INTO kv(k,v) VALUES('routes',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                     (json.dumps(routes),))
        self.store.x("INSERT INTO kv(k,v) VALUES(?,?)",
                     ("models:antigravity", json.dumps({"at": time.time(), "models": [ARGON, FLASH]})))
        self.attempts = []

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _fake_agy_script(self, exhausted: set[str]) -> Path:
        script = self.tmp / f"fake_agy_{time.time_ns()}.py"
        script.write_text(
            "import sys\n"
            f"exhausted = {exhausted!r}\n"
            "argv = sys.argv[1:]\n"
            "model = None\n"
            "if '--model' in argv:\n"
            "    model = argv[argv.index('--model') + 1]\n"
            "open(sys.argv[0] + '.log', 'a', encoding='utf-8').write((model or 'default') + '\\n')\n"
            f"quota = {QUOTA!r}\n"
            "if model in exhausted:\n"
            "    sys.stdout.write(quota + '\\n')\n"
            "    sys.exit(1)\n"
            "sys.stdout.write('ok from ' + (model or 'default') + '\\n')\n"
            "sys.exit(0)\n",
            encoding="utf-8",
        )
        return script

    def _patch_build(self, script: Path):
        def build(route_id, mode, cwd, out_file, model=None, prompt=None, images=None, study=None):
            self.attempts.append(model)
            return [sys.executable, str(script), "--model", model or ARGON, f"-p={prompt or ''}"]

        return patch.object(providers, "build_argv", side_effect=build)

    def test_argon_quota_falls_back_to_flash_on_send(self):
        script = self._fake_agy_script({ARGON})
        with self._patch_build(script):
            tid = self.sup.create(self.p, "antigravity", "hello", mode="chat", timeout=30)
            t = _wait_terminal(self.sup, tid)
        self.assertEqual(t["state"], "COMPLETED")
        self.assertEqual(self.attempts, [ARGON, FLASH])
        cp = json.loads(t["checkpoint"] or "{}")
        self.assertEqual(cp["model"], FLASH)
        self.assertEqual(cp["models_tried"], [ARGON, FLASH])
        self.assertEqual(cp["model_in_use"], FLASH)
        self.assertEqual([e["model"] for e in cp["models_exhausted"]], [ARGON])
        self.assertEqual(providers._model_state(self.store, "antigravity")["model_in_use"], FLASH)
        route = providers.cached(self.store)["antigravity"]
        self.assertEqual(route["state"], "READY_INCLUDED")
        self.assertEqual(route["model_in_use"], FLASH)

    def test_all_models_quota_marks_unavailable_without_retry(self):
        script = self._fake_agy_script({ARGON, FLASH})
        with self._patch_build(script):
            tid = self.sup.create(self.p, "antigravity", "hello", mode="chat", timeout=30)
            t = _wait_terminal(self.sup, tid)
        self.assertEqual(t["state"], "FAILED")
        self.assertEqual(self.attempts, [ARGON, FLASH])
        cp = json.loads(t["checkpoint"] or "{}")
        self.assertEqual(cp["models_tried"], [ARGON, FLASH])
        self.assertIsNone(cp.get("model_in_use"))
        self.assertEqual({e["model"] for e in cp["models_exhausted"]}, {ARGON, FLASH})
        self.assertIsNone(cp.get("retried_as"))
        self.assertNotIn("retried automatically", t["error"] or "")
        ver = json.loads(self.store.one("SELECT v FROM kv WHERE k=?", ("verify:antigravity",))["v"])
        self.assertFalse(ver["ok"])
        self.assertEqual(ver["state"], "UNAVAILABLE")
        self.assertEqual(providers.cached(self.store)["antigravity"]["state"], "UNAVAILABLE")

    def test_nonquota_failure_does_not_advance_model(self):
        script = self.tmp / f"fake_agy_auth_{time.time_ns()}.py"
        script.write_text(
            "import sys\n"
            "sys.stdout.write('authentication required\\n')\n"
            "sys.exit(1)\n",
            encoding="utf-8",
        )
        with self._patch_build(script):
            tid = self.sup.create(self.p, "antigravity", "hello", mode="chat", timeout=30)
            t = _wait_terminal(self.sup, tid)
        self.assertEqual(t["state"], "FAILED")
        self.assertEqual(self.attempts, [ARGON])
        self.assertEqual(providers._model_state(self.store, "antigravity")["models_exhausted"], [])

    def test_services_send_uses_fallback(self):
        script = self._fake_agy_script({ARGON})
        cid = self.svc.new_conversation(self.p["id"])
        with self._patch_build(script):
            out = self.svc.send(self.p["id"], cid["id"], "ping", [], "antigravity")
            t = _wait_terminal(self.sup, out["task_id"])
        self.assertEqual(t["state"], "COMPLETED")
        self.assertEqual(self.attempts, [ARGON, FLASH])
        self.assertEqual(json.loads(t["checkpoint"])["model_in_use"], FLASH)

    def test_project_model_override_skipped_when_exhausted(self):
        self.store.x("UPDATE projects SET model=? WHERE id=?", (ARGON, self.p["id"]))
        self.p = self.svc.project(self.p["id"])
        providers.record_model_quota(self.store, "antigravity", ARGON, 1, QUOTA)
        script = self._fake_agy_script(set())
        with self._patch_build(script):
            tid = self.sup.create(self.p, "antigravity", "hello", mode="chat", timeout=30)
            t = _wait_terminal(self.sup, tid)
        self.assertEqual(t["state"], "COMPLETED")
        self.assertEqual(self.attempts, [FLASH])
        self.assertEqual(json.loads(t["checkpoint"])["model_in_use"], FLASH)

    def test_catalog_failure_refuses_dispatch(self):
        self.store.x("DELETE FROM kv WHERE k=?", ("models:antigravity",))
        with patch.object(providers, "_agy_cmd", return_value=["fake-agy"]), \
                patch.object(providers, "_contained", return_value=(1, "listing failed")):
            tid = self.sup.create(self.p, "antigravity", "hello", mode="chat", timeout=30)
            t = _wait_terminal(self.sup, tid)
        self.assertEqual(t["state"], "FAILED")
        self.assertIn("model list unavailable", t["error"])
        self.assertEqual(self.attempts, [])

    def test_cancel_during_quota_fallback_gap_skips_next_model(self):
        """Stop between attempts (no registered process) must not launch Flash."""
        script = self._fake_agy_script({ARGON})
        tid_box: list[str] = []
        real_record = providers.record_model_quota

        def record_then_cancel(store, rid, model, code, output):
            ok = real_record(store, rid, model, code, output)
            if ok and model == ARGON and tid_box:
                # Process already deregistered; cancel must still stick before Flash launches.
                self.assertIsNone(self.sup.procs.get(tid_box[0]))
                self.assertTrue(self.sup.cancel(tid_box[0]))
            return ok

        with self._patch_build(script), \
                patch.object(providers, "record_model_quota", side_effect=record_then_cancel):
            tid = self.sup.create(self.p, "antigravity", "hello", mode="chat", timeout=30)
            tid_box.append(tid)
            t = _wait_terminal(self.sup, tid)
        self.assertEqual(t["state"], "CANCELLED")
        self.assertEqual(self.attempts, [ARGON])
        self.assertIn(tid, self.sup.cancel_flags)

    def test_output_offsets_survive_model_fallback(self):
        """Terminal/chat poll offsets must still see Flash after consuming Argon's quota bytes."""
        script = self._fake_agy_script({ARGON})
        with self._patch_build(script):
            tid = self.sup.create(self.p, "antigravity", "hello", mode="chat", timeout=30)
            t = _wait_terminal(self.sup, tid)
        self.assertEqual(t["state"], "COMPLETED")
        full, end = self.sup.output(tid, 0)
        self.assertIn("RESOURCE_EXHAUSTED", full)
        self.assertIn("ok from " + FLASH, full)
        # Simulate a watcher that already consumed the quota line, then polls again.
        quota_at = full.index("RESOURCE_EXHAUSTED")
        offset = full.index("\n", quota_at) + 1
        self.assertGreater(offset, 0)
        self.assertLess(offset, end)
        rest, final = self.sup.output(tid, offset)
        self.assertEqual(final, end)
        self.assertIn("ok from " + FLASH, rest)
        self.assertNotIn("RESOURCE_EXHAUSTED", rest)


if __name__ == "__main__":
    unittest.main()
