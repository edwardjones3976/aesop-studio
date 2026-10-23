"""LM Studio local route: client talks only to loopback, strips hidden reasoning, reports failures."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CLIENT = Path(__file__).resolve().parent.parent / "aesop_studio" / "local_llm_client.py"


class FakeLMStudio(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeLMStudio.seen.append(body)
        out = json.dumps({"choices": [{"message": {"content": "<think>secret plan</think>\nThe answer is 42."}}]})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out.encode())


class TestLocalClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        cls.port = s.getsockname()[1]
        s.close()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", cls.port), FakeLMStudio)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def run_client(self, port):
        out = Path(tempfile.mkdtemp()) / "o.txt"
        env = dict(os.environ, AESOP_LMSTUDIO_PORT=str(port))
        p = subprocess.run([sys.executable, "-I", str(CLIENT), "qwen-test", str(out)], input="Question?",
                           capture_output=True, text=True, env=env, timeout=60)
        return p, out

    def test_answer_without_hidden_reasoning(self):
        p, out = self.run_client(self.port)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(out.read_text(encoding="utf-8"), "The answer is 42.")
        self.assertNotIn("secret plan", p.stdout)
        self.assertEqual(FakeLMStudio.seen[-1]["model"], "qwen-test")

    def test_server_down_fails_cleanly(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        dead = s.getsockname()[1]
        s.close()
        p, out = self.run_client(dead)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("local model error", p.stderr)
        self.assertFalse(out.exists())

    def test_lane_listed(self):
        os.environ["AESOP_PROBE_OFFLINE"] = "1"
        from aesop_studio import lanes
        self.assertIn("LM Studio (local)", lanes.DOCUMENTED_EXAMPLE)
        self.assertTrue(any(c[0] == "lmstudio" for c in lanes.CATALOG))


if __name__ == "__main__":
    unittest.main()
