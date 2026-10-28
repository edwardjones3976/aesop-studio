"""Grok API (xAI Responses) route: key presence, pricing bounds, and the shared stream body."""
import os
import unittest
from unittest.mock import patch

os.environ["AESOP_PROBE_OFFLINE"] = "1"
os.environ["AESOP_SIMULATED_ROUTE"] = "1"

from aesop_studio import openai_api, providers, xai_api  # noqa: E402


class TestXaiRoute(unittest.TestCase):
    def test_key_presence_drives_route_state(self):
        with patch.dict(os.environ, {"XAI_API_KEY": "k"}):
            self.assertTrue(xai_api.key_present())
            self.assertIn("XAI_API_KEY", xai_api.key_source())
        with patch.dict(os.environ, {"XAI_API_KEY": "", "AESOP_XAI_KEY_FILE": "C:/nope/xai.dpapi"}):
            self.assertFalse(xai_api.key_present())
            with self.assertRaises(openai_api.ApiError):
                xai_api.resolve_key()

    def test_prices_are_xai_not_openai(self):
        cap = xai_api.max_cost("grok-4.7", 1000, 100)
        pin, pout = xai_api.PRICES["grok-4.7"]
        self.assertAlmostEqual(cap, round(((1064 * pin + 100 * pout) / 1e6) * 1.10 + 0.00005, 4), places=3)
        self.assertNotIn("grok-4.7", openai_api.PRICES)
        with self.assertRaises(openai_api.ApiError):
            xai_api.max_cost("gpt-6.1-sol", 10, 10)  # an OpenAI model is never billed on the xAI table
        self.assertEqual(xai_api.actual_cost("grok-4.3", {"input_tokens": 1_000_000, "output_tokens": 0}), 1.25)

    def test_route_listed_with_images_and_budgets(self):
        from aesop_studio import browse_agent, services
        self.assertIn("xai-api", services.IMAGE_ROUTES)
        self.assertIn("xai-api", browse_agent.VISION_ROUTES)
        self.assertEqual(providers.display_name("xai-api"), "Grok API")
        self.assertIn("XAI_API_KEY", providers.BILLING_ENV)

    def test_stream_targets_xai_host_without_reasoning_field(self):
        seen = {}

        def fake_stream(prompt, model, max_output, on_delta, cancel, timeout, key=None, images=None, host=None,
                        reasoning_effort="x"):
            seen.update(host=host, key=key, reasoning=reasoning_effort, images=images)
            return {"text": "ok", "usage": {"input_tokens": 1, "output_tokens": 1}, "status": "completed"}
        with patch.object(openai_api, "stream", fake_stream), patch.dict(os.environ, {"XAI_API_KEY": "k"}):
            import threading
            r = xai_api.stream("p", "grok-4.7", 10, lambda d: None, threading.Event(), 5, images=["data:x"])
        self.assertEqual(r["status"], "completed")
        self.assertEqual(seen["host"], "api.x.ai")
        self.assertEqual(seen["key"], "k")
        self.assertIsNone(seen["reasoning"])
        self.assertEqual(seen["images"], ["data:x"])


if __name__ == "__main__":
    unittest.main()
