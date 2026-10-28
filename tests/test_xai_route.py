"""Grok API (xAI Responses) route: key presence, pricing bounds, and the shared stream body."""

import json
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

os.environ["AESOP_PROBE_OFFLINE"] = "1"
os.environ["AESOP_SIMULATED_ROUTE"] = "1"

from aesop_studio import ledger, openai_api, providers, xai_api  # noqa: E402
from aesop_studio.services import Services  # noqa: E402
from aesop_studio.store import Store  # noqa: E402
from aesop_studio.tasks import TERMINAL, Supervisor  # noqa: E402


class TestXaiRoute(unittest.TestCase):
    def test_key_presence_drives_route_state(self):
        with patch.dict(os.environ, {"XAI_API_KEY": "k"}):
            self.assertTrue(xai_api.key_present())
            self.assertIn("XAI_API_KEY", xai_api.key_source())
        with patch.dict(
            os.environ, {"XAI_API_KEY": "", "AESOP_XAI_KEY_FILE": "C:/nope/xai.dpapi"}
        ):
            self.assertFalse(xai_api.key_present())
            with self.assertRaises(openai_api.ApiError):
                xai_api.resolve_key()

    def test_prices_are_xai_not_openai(self):
        cap = xai_api.max_cost("grok-4.7", 1000, 100)
        pin, pout = xai_api.PRICES["grok-4.7"]
        self.assertAlmostEqual(
            cap, round(((1064 * pin + 100 * pout) / 1e6) * 1.10 + 0.00005, 4), places=3
        )
        self.assertNotIn("grok-4.7", openai_api.PRICES)
        with self.assertRaises(openai_api.ApiError):
            xai_api.max_cost(
                "gpt-6.1-sol", 10, 10
            )  # an OpenAI model is never billed on the xAI table
        self.assertEqual(
            xai_api.actual_cost(
                "grok-4.3", {"input_tokens": 1_000_000, "output_tokens": 0}
            ),
            1.25,
        )

    def test_route_listed_with_images_and_budgets(self):
        from aesop_studio import browse_agent, services

        self.assertIn("xai-api", services.IMAGE_ROUTES)
        self.assertIn("xai-api", browse_agent.VISION_ROUTES)
        self.assertEqual(providers.display_name("xai-api"), "Grok API")
        self.assertIn("XAI_API_KEY", providers.BILLING_ENV)

    def test_stream_targets_xai_host_without_reasoning_field(self):
        seen = {}

        def fake_stream(
            prompt,
            model,
            max_output,
            on_delta,
            cancel,
            timeout,
            key=None,
            images=None,
            host=None,
            reasoning_effort="x",
        ):
            seen.update(host=host, key=key, reasoning=reasoning_effort, images=images)
            return {
                "text": "ok",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "status": "completed",
            }

        with (
            patch.object(openai_api, "stream", fake_stream),
            patch.dict(os.environ, {"XAI_API_KEY": "k"}),
        ):
            r = xai_api.stream(
                "p",
                "grok-4.7",
                10,
                lambda d: None,
                threading.Event(),
                5,
                images=["data:x"],
            )
        self.assertEqual(r["status"], "completed")
        self.assertEqual(seen["host"], "api.x.ai")
        self.assertEqual(seen["key"], "k")
        self.assertIsNone(seen["reasoning"])
        self.assertEqual(seen["images"], ["data:x"])


class FakeResponses(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeResponses.seen.append(
            {"auth": self.headers.get("Authorization"), "body": body}
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for c in ["The CLI ", "is ripple", ", due Friday."]:
            self.wfile.write(
                f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': c})}\n\n".encode()
            )
            self.wfile.flush()
            time.sleep(0.05)
        done = {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "usage": {"input_tokens": 1200, "output_tokens": 300},
            },
        }
        self.wfile.write(f"data: {json.dumps(done)}\n\n".encode())


class TestXaiApiDispatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        cls.fake = ThreadingHTTPServer(("127.0.0.1", port), FakeResponses)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        os.environ["AESOP_OPENAI_TEST_BASE"] = f"http://127.0.0.1:{port}"
        os.environ["XAI_API_KEY"] = "test-xai"

    @classmethod
    def tearDownClass(cls):
        cls.fake.shutdown()
        os.environ.pop("XAI_API_KEY", None)
        os.environ.pop("AESOP_OPENAI_TEST_BASE", None)

    def setUp(self):
        FakeResponses.seen.clear()
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-xai-"))
        (self.tmp / "p").mkdir()
        self.store = Store(self.tmp / "data")
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        providers.refresh(self.store)
        self.p = self.svc.create_project("P", str(self.tmp / "p"), "xai-api")
        self.c = self.svc.new_conversation(self.p["id"])

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def send(self, text="Which CLI?"):
        r = self.svc.send(self.p["id"], self.c["id"], text, [], None)
        end = time.time() + 20
        while self.sup.get(r["task_id"])["state"] not in TERMINAL and time.time() < end:
            time.sleep(0.05)
        return self.sup.get(r["task_id"])

    def test_runtime_limit_streams_and_settles(self):
        ledger.set_runtime_limit(self.store, 1.0)
        providers.refresh(self.store)
        t = self.send()
        self.assertEqual(t["state"], "COMPLETED", t.get("error"))
        row = self.store.one("SELECT * FROM ledger WHERE task_ref=?", (t["id"],))
        self.assertEqual(row["provider"], "xai")
        self.assertGreater(row["reservation_usd"], 0)
        self.assertGreater(row["settled_usd"], 0)
        pin, pout = xai_api.PRICES[xai_api.DEFAULT_MODEL]
        self.assertAlmostEqual(
            row["settled_usd"], (1200 * pin + 300 * pout) / 1e6, places=9
        )


if __name__ == "__main__":
    unittest.main()
