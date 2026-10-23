"""Metered OpenAI route against a local fake Responses API (offline simulation, never a live call)."""
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

os.environ["AESOP_SIMULATED_ROUTE"] = "1"
os.environ["AESOP_PROBE_OFFLINE"] = "1"  # never launch real provider CLIs in tests

from aesop_studio import ledger, openai_api, providers  # noqa: E402
from aesop_studio.services import Services  # noqa: E402
from aesop_studio.store import Store  # noqa: E402
from aesop_studio.tasks import TERMINAL, Supervisor  # noqa: E402


class FakeResponses(BaseHTTPRequestHandler):
    mode = "ok"
    seen = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeResponses.seen.append({"auth": self.headers.get("Authorization"), "body": body})
        if FakeResponses.mode == "401":
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"Incorrect API key provided"}}')
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        if FakeResponses.mode == "weird":
            self.wfile.write(b"data: [1, 2, 3]\n\ndata: 42\n\n")
        chunks = ["The CLI ", "is ripple", ", due Friday."] if FakeResponses.mode in ("ok", "weird") else ["x"] * 400
        for c in chunks:
            self.wfile.write(f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': c})}\n\n".encode())
            self.wfile.flush()
            time.sleep(0.05)
        done = {"type": "response.completed", "response": {"status": "completed",
                                                           "usage": {"input_tokens": 1200, "output_tokens": 300}}}
        self.wfile.write(f"data: {json.dumps(done)}\n\n".encode())


class TestOpenAIRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        cls.fake = ThreadingHTTPServer(("127.0.0.1", port), FakeResponses)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        os.environ["AESOP_OPENAI_TEST_BASE"] = f"http://127.0.0.1:{port}"
        os.environ["OPENAI_API_KEY"] = "test-not-a-real-key"

    @classmethod
    def tearDownClass(cls):
        cls.fake.shutdown()
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("AESOP_OPENAI_TEST_BASE", None)

    def setUp(self):
        FakeResponses.mode = "ok"
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-oai-"))
        (self.tmp / "p").mkdir()
        self.store = Store(self.tmp / "data")
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        providers.refresh(self.store)
        self.p = self.svc.create_project("P", str(self.tmp / "p"), "openai-api")
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

    def test_disabled_until_owner_enables(self):
        self.assertEqual(providers.cached(self.store)["openai-api"]["state"], "READY_METERED_DISABLED")
        t = self.send()
        self.assertEqual(t["state"], "BLOCKED_OWNER")
        self.assertEqual(FakeResponses.seen and FakeResponses.seen[-1]["body"].get("input") == "x", False)

    def test_runtime_limit_streams_and_settles_actual_cost(self):
        ledger.set_runtime_limit(self.store, 1.0)
        self.assertEqual(providers.cached(self.store)["openai-api"]["state"], "READY_METERED")
        t = self.send()
        self.assertEqual(t["state"], "COMPLETED", t["error"])
        body = FakeResponses.seen[-1]["body"]
        self.assertEqual(body["model"], openai_api.DEFAULT_MODEL)
        self.assertEqual(body["max_output_tokens"], openai_api.DEFAULT_MAX_OUTPUT)
        self.assertFalse(body["store"])
        self.assertEqual(self.sup.output(t["id"])[0], "The CLI is ripple, due Friday.")
        row = self.store.one("SELECT * FROM ledger WHERE task_ref=?", (t["id"],))
        self.assertEqual(row["purpose"], "runtime")
        self.assertAlmostEqual(row["settled_usd"], (1200 * 0.10 + 300 * 0.50) / 1e6, places=9)
        self.assertGreaterEqual(row["reservation_usd"], row["settled_usd"])
        msg = self.svc.messages(self.p["id"], self.c["id"])[-1]
        self.assertEqual(msg["status"], "generated")
        self.assertIn("cost_usd", msg["meta"])

    def test_mission_permit_uses_mission_envelope(self):
        ledger.set_permit(self.store, True)
        t = self.send()
        self.assertEqual(t["state"], "COMPLETED")
        self.assertEqual(self.store.one("SELECT purpose FROM ledger WHERE task_ref=?", (t["id"],))["purpose"], "mission")

    def test_limit_too_small_blocks_before_dispatch(self):
        ledger.set_runtime_limit(self.store, 0.0001)
        n = len(FakeResponses.seen)
        t = self.send()
        self.assertEqual(t["state"], "BLOCKED_OWNER")
        self.assertEqual(len(FakeResponses.seen), n)  # nothing sent

    def test_auth_error_settles_zero(self):
        ledger.set_runtime_limit(self.store, 1.0)
        FakeResponses.mode = "401"
        t = self.send()
        self.assertEqual(t["state"], "FAILED")
        self.assertIn("Incorrect API key", t["error"])
        self.assertEqual(ledger.totals(self.store)["runtime_month_outstanding"], 0)

    def test_cancel_keeps_exposure(self):
        ledger.set_runtime_limit(self.store, 1.0)
        FakeResponses.mode = "slow"
        r = self.svc.send(self.p["id"], self.c["id"], "long", [], None)
        time.sleep(0.5)
        self.assertTrue(self.sup.cancel(r["task_id"]))
        end = time.time() + 20
        while self.sup.get(r["task_id"])["state"] not in TERMINAL and time.time() < end:
            time.sleep(0.05)
        self.assertEqual(self.sup.get(r["task_id"])["state"], "CANCELLED")
        self.assertGreater(ledger.totals(self.store)["runtime_month_outstanding"], 0)

    def test_unknown_model_refused_and_key_never_logged(self):
        with self.assertRaises(openai_api.ApiError):
            openai_api.max_cost("gpt-unknown", 100, 100)
        ledger.set_runtime_limit(self.store, 1.0)
        t = self.send()
        blob = json.dumps(self.store.q("SELECT * FROM tasks")) + json.dumps(self.store.q("SELECT * FROM events"))
        self.assertNotIn("test-not-a-real-key", blob)
        self.assertNotIn("test-not-a-real-key", self.sup.output(t["id"])[0])

    def test_non_object_stream_events_ignored(self):
        ledger.set_runtime_limit(self.store, 1.0)
        FakeResponses.mode = "weird"
        t = self.send()
        self.assertEqual(t["state"], "COMPLETED", t["error"])

    def test_non_openai_metered_never_allowed(self):
        ledger.set_runtime_limit(self.store, 5)
        with self.assertRaises(ledger.BudgetError):
            ledger.reserve(self.store, "anthropic", "x", "metered", 0.01)


if __name__ == "__main__":
    unittest.main()


class TestReviewFixes(unittest.TestCase):
    def test_reservation_bounds_any_script_by_bytes(self):
        cjk = ("字" * 10000).encode("utf-8")
        pin, pout = openai_api.PRICES["gpt-6-astra"]
        floor = (10000 * pin) / 1e6  # at worst one token per character
        self.assertGreater(openai_api.max_cost("gpt-6-astra", len(cjk), 0), floor)
        with self.assertRaises(openai_api.ApiError):
            openai_api.max_cost("gpt-6-luna", openai_api.MAX_PROMPT_BYTES + 1, 100)

    def test_split_secret_redacted_in_stream_log(self):
        from aesop_studio.tasks import _RedactingLog
        d = Path(tempfile.mkdtemp())
        log = _RedactingLog(str(d / "o.log"))
        secret = "sk-proj-" + "a1b2c3d4e5" * 4
        text = "Here is the value you pasted: " + secret + " and some more words " * 30
        for i in range(0, len(text), 3):  # 3-char deltas split the secret many times
            log.write(text[i:i + 3])
        log.close()
        out = (d / "o.log").read_text(encoding="utf-8")
        self.assertNotIn("a1b2c3d4e5a1b2", out)
        self.assertIn("[REDACTED]", out)
        self.assertIn("some more words", out)
        shutil.rmtree(d, ignore_errors=True)

    def test_test_override_refuses_real_keys(self):
        old = os.environ.get("OPENAI_API_KEY")
        os.environ["AESOP_OPENAI_TEST_BASE"] = "http://127.0.0.1:9"
        os.environ["OPENAI_API_KEY"] = "sk-real-looking-key-0000000000"
        try:
            with self.assertRaises(openai_api.ApiError):
                openai_api.resolve_key()
        finally:
            os.environ.pop("AESOP_OPENAI_TEST_BASE", None)
            if old is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = old

    def test_resolve_ambiguous_and_flag_overshoot(self):
        tmp = Path(tempfile.mkdtemp())
        s = Store(tmp / "d")
        ledger.set_runtime_limit(s, 1.0)
        lid = ledger.reserve(s, "openai", "openai-api", "metered", 0.01, purpose="runtime")
        with self.assertRaises(ledger.BudgetError):
            ledger.resolve(s, lid, 0.001)  # not ambiguous yet
        ledger.settle(s, lid, None)
        self.assertEqual(ledger.totals(s)["runtime_month_outstanding"], 0.01)
        ledger.resolve(s, lid, 0.002, "from usage dashboard")
        t = ledger.totals(s)
        self.assertEqual(t["runtime_month_outstanding"], 0)
        self.assertAlmostEqual(t["runtime_month_settled"], 0.002)
        lid2 = ledger.reserve(s, "openai", "openai-api", "metered", 0.001, purpose="runtime")
        ledger.settle(s, lid2, 0.005)
        self.assertEqual(len(s.q("SELECT * FROM events WHERE kind='reservation_overshoot'")), 1)
        s.close()
        shutil.rmtree(tmp, ignore_errors=True)
