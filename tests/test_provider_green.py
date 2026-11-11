"""WO-20261027-002 regressions; all provider processes and key checks are fake."""
import copy
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from aesop_studio import ledger, providers
from aesop_studio.server import Handler
from aesop_studio.store import Store


ARGON = "gemini-4-argon-high"
FLASH = "gemini-3.8-flash-low"
QUOTA = "RESOURCE_EXHAUSTED 429 Individual quota reached. Resets in 81h"


class ProviderGreen(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="aesop-provider-green-")
        self.addCleanup(tmp.cleanup)
        self.store = Store(tmp.name)
        self.addCleanup(self.store.close)

    def fake_agy(self, argv, timeout, **kwargs):
        if argv[-1] == "models":
            return 0, f"Available models:\n  {FLASH}\n* {ARGON} (default)\n"
        if argv[-1] == "--version":
            return 0, "1.0.0"
        model = argv[argv.index("--model") + 1] if "--model" in argv else ARGON
        self.attempts.append(model)
        return (1, QUOTA) if model in self.exhausted else (0, providers.VERIFY_TOKEN)

    def fake_routes(self):
        # Exercise the real probe's verification-to-readiness mapping without calling any CLI or key source.
        for name in ("_codex_cmd", "_claude_cmd", "_cursor_cmd", "_copilot_cmd", "_grok_cmd", "_zai_cmd"):
            self.enterContext(patch.object(providers, name, return_value=None))
        self.enterContext(patch.object(providers, "_agy_cmd", return_value=["fake-agy"]))
        self.enterContext(patch.dict(os.environ, {"AESOP_PROBE_OFFLINE": "0"}))
        self.enterContext(patch("aesop_studio.openai_api.key_present", return_value=False))
        self.enterContext(patch("aesop_studio.perplexity_api.key_present", return_value=False))
        self.enterContext(patch("aesop_studio.research_routes.status",
                                return_value={"firecrawl": False, "perplexity": False}))
        self.enterContext(patch("aesop_studio.research_routes.key_problem", return_value=None))
        self.attempts, self.exhausted = [], {ARGON}
        return self.enterContext(patch.object(providers, "_contained", side_effect=self.fake_agy))

    def test_refresh_and_verify_responses_overlay_mission_permit(self):
        ledger.set_runtime_limit(self.store, 0)
        raw = {rid: {"state": "READY_METERED_DISABLED", "incremental_cost_status": "metered; test"}
               for rid in ("perplexity", "openai-api", "perplexity-orchestrator")}
        handler = SimpleNamespace(app=SimpleNamespace(store=self.store), json=Mock())
        with patch.object(providers, "probe", side_effect=lambda store: copy.deepcopy(raw)), \
                patch.object(providers, "verify_live", return_value={"ok": True}):
            for permit in (True, False):
                ledger.set_permit(self.store, permit)
                expected = "READY_METERED" if permit else "READY_METERED_DISABLED"
                Handler.routes_refresh(handler, None)
                self.assertEqual({r["state"] for r in handler.json.call_args.args[0].values()}, {expected})
                Handler.route_verify(handler, None, "antigravity")
                routes = handler.json.call_args.args[0]["routes"]
                self.assertEqual({r["state"] for r in routes.values()}, {expected})
                self.assertEqual({r["state"] for r in providers.cached(self.store).values()}, {expected})
                stored = json.loads(self.store.one("SELECT v FROM kv WHERE k='routes'")["v"])
                self.assertEqual({r["state"] for r in stored.values()}, {"READY_METERED_DISABLED"})

    def test_argon_quota_falls_back_to_flash_and_stays_ready(self):
        self.fake_routes()
        rec = providers.verify_live(self.store, "antigravity")
        self.assertTrue(rec["ok"])
        self.assertEqual(self.attempts, [ARGON, FLASH])
        self.assertEqual(rec["model_in_use"], FLASH)
        self.assertEqual([e["model"] for e in rec["models_exhausted"]], [ARGON])
        self.assertEqual(rec["models_exhausted"][0]["reset_text"], "Resets in 81h")
        for routes in (providers.refresh(self.store), providers.cached(self.store)):
            route = routes["antigravity"]
            self.assertEqual(route["state"], "READY_INCLUDED")
            self.assertEqual(route["model_in_use"], FLASH)
            self.assertEqual(route["models_exhausted"], rec["models_exhausted"])

    def test_all_models_quota_are_recorded_before_unavailable(self):
        self.fake_routes()
        self.exhausted = {ARGON, FLASH}
        rec = providers.verify_live(self.store, "antigravity")
        self.assertFalse(rec["ok"])
        self.assertEqual(self.attempts, [ARGON, FLASH])
        self.assertEqual({e["model"] for e in rec["models_exhausted"]}, {ARGON, FLASH})
        self.assertIsNone(rec["model_in_use"])
        self.assertEqual(providers.refresh(self.store)["antigravity"]["state"], "UNAVAILABLE")
        providers.verify_live(self.store, "antigravity")
        self.assertEqual(self.attempts, [ARGON, FLASH])  # no replay before reset

    def test_exhaustion_expires_at_reset_or_after_one_day(self):
        self.fake_routes()
        now = time.time()
        with patch.object(providers.time, "time", return_value=now):
            providers.record_model_quota(self.store, "antigravity", ARGON, 1, QUOTA)
            providers.record_model_quota(self.store, "antigravity", FLASH, 1, "HTTP 429")
        with patch.object(providers.time, "time", return_value=now + 86400):
            self.assertEqual(providers.available_models(self.store, "antigravity"), [FLASH])
        with patch.object(providers.time, "time", return_value=now + 81 * 3600):
            self.assertEqual(providers.available_models(self.store, "antigravity"), [ARGON, FLASH])

    def test_compound_reset_duration(self):
        now = time.time()
        with patch.object(providers.time, "time", return_value=now):
            providers.record_model_quota(self.store, "antigravity", ARGON, 1,
                                         "quota reached; Resets in 1h 30m 5s")
        entry = providers._model_state(self.store, "antigravity")["models_exhausted"][0]
        self.assertEqual(entry["expires_at"], now + 5405)

    def test_absolute_reset_and_expired_route_need_reverification(self):
        self.fake_routes()
        self.exhausted = {ARGON, FLASH}
        providers.verify_live(self.store, "antigravity")
        providers.refresh(self.store)
        with patch.object(providers.time, "time", return_value=time.time() + 82 * 3600):
            route = providers.cached(self.store)["antigravity"]
            self.assertEqual(route["models_exhausted"], [])
            self.assertEqual(route["state"], "UNVERIFIED")
        now = datetime(2026, 10, 27, tzinfo=timezone.utc).timestamp()
        with patch.object(providers.time, "time", return_value=now):
            providers.record_model_quota(self.store, "antigravity", ARGON, 1,
                                         "429; Resets at 2026-10-27T01:00:00Z")
            entry = next(e for e in providers._model_state(self.store, "antigravity")["models_exhausted"]
                         if e["model"] == ARGON)
            self.assertEqual(entry["expires_at"], now + 3600)

    def test_catalog_cache_ttl_refresh_and_preferences(self):
        call = self.fake_routes()
        now = time.time()
        with patch.object(providers.time, "time", return_value=now):
            self.assertEqual(providers.model_catalog(self.store, "antigravity"), [ARGON, FLASH])
            providers.model_catalog(self.store, "antigravity")
            self.assertEqual(call.call_count, 1)
            providers.model_catalog(self.store, "antigravity", refresh=True)
            self.assertEqual(call.call_count, 2)
        with patch.object(providers.time, "time", return_value=now + 3600):
            providers.model_catalog(self.store, "antigravity")
            self.assertEqual(call.call_count, 3)
        self.store.x("INSERT INTO kv(k,v) VALUES(?,?)",
                     ("model-preferences:antigravity", json.dumps([FLASH, "invented-model"])))
        self.assertEqual(providers.model_catalog(self.store, "antigravity"), [FLASH, ARGON])

    def test_requested_exhausted_model_is_skipped(self):
        self.fake_routes()
        providers.record_model_quota(self.store, "antigravity", ARGON, 1, QUOTA)
        self.assertEqual(providers.available_models(self.store, "antigravity", ARGON), [FLASH])
        with self.assertRaises(RuntimeError):
            providers.available_models(self.store, "antigravity", "invented-model")

    def test_catalog_failure_does_not_dispatch_default_or_stale_models(self):
        self.fake_routes()
        self.store.x("INSERT INTO kv(k,v) VALUES(?,?)",
                     ("models:antigravity", json.dumps({"at": time.time() - 3601, "models": [ARGON, FLASH]})))
        with patch.object(providers, "_contained", return_value=(1, "model listing failed")) as call:
            rec = providers.verify_live(self.store, "antigravity")
        self.assertFalse(rec["ok"])
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.args[0], ["fake-agy", "models"])
        self.assertEqual(rec["models_exhausted"], [])
        self.assertEqual(providers.refresh(self.store)["antigravity"]["state"], "UNVERIFIED")

    def test_deadline_does_not_exhaust_untried_models(self):
        self.fake_routes()
        providers.model_catalog(self.store, "antigravity")
        now = [time.time()]

        def slow_quota(argv, timeout, **kwargs):
            now[0] += 181
            return 1, QUOTA

        with patch.object(providers.time, "time", side_effect=lambda: now[0]), \
                patch.object(providers, "_contained", side_effect=slow_quota) as call:
            rec = providers.verify_live(self.store, "antigravity")
        self.assertEqual(call.call_count, 1)
        self.assertEqual(rec["state"], "UNVERIFIED")
        self.assertEqual([e["model"] for e in rec["models_exhausted"]], [ARGON])

    def test_nonquota_failure_and_timeout_are_not_replayed(self):
        self.fake_routes()
        providers.model_catalog(self.store, "antigravity")
        for code, output in ((1, "authentication required"), (-1, "timed out after HTTP 429")):
            with self.subTest(code=code), patch.object(providers, "_contained", return_value=(code, output)) as call:
                rec = providers.verify_live(self.store, "antigravity")
                self.assertFalse(rec["ok"])
                self.assertEqual(call.call_count, 1)
                self.assertEqual(rec["models_exhausted"], [])

    def test_successful_answer_mentioning_quota_is_not_exhaustion(self):
        self.assertFalse(providers.record_model_quota(self.store, "antigravity", ARGON, 0, QUOTA))
        self.assertEqual(providers._model_state(self.store, "antigravity")["models_exhausted"], [])


if __name__ == "__main__":
    unittest.main()
