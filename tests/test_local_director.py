"""Exact local Director routes: pinned profile, loopback transports and Aesop route plumbing."""
from __future__ import annotations

import hashlib
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

from aesop_studio import lanes, providers

ROOT = Path(__file__).resolve().parent.parent
CLIENT = ROOT / "aesop_studio" / "local_director_client.py"
PROFILE = ROOT / "aesop_studio" / "director_profile.json"


class LocalDirectorServer(BaseHTTPRequestHandler):
    seen: list[tuple[str, dict]] = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        data = ({"data": [{"id": "director-20261102"}]} if self.path == "/v1/models"
                else {"models": [{"name": "director:20261102"}]})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.seen.append((self.path, body))
        text = "<think>private scratch</think>\nDirector answer."
        data = ({"choices": [{"message": {"content": text}}]} if self.path == "/v1/chat/completions"
                else {"message": {"content": text}})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())


class TestLocalDirector(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        cls.port = sock.getsockname()[1]
        sock.close()
        cls.server = ThreadingHTTPServer(("127.0.0.1", cls.port), LocalDirectorServer)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def run_client(self, backend: str, model: str):
        out = Path(tempfile.mkdtemp()) / "answer.txt"
        env = dict(os.environ, **{f"AESOP_{backend.upper()}_PORT": str(self.port)})
        proc = subprocess.run([sys.executable, "-I", str(CLIENT), backend, model, str(out)], input="Question?",
                              capture_output=True, text=True, env=env, timeout=30)
        return proc, out

    def test_exact_role_profile_and_both_loopback_transports(self):
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(profile["system"].encode()).hexdigest(), profile["role_sha256"])
        for backend, model, endpoint in (("lmstudio", "director-20261102", "/v1/chat/completions"),
                                         ("ollama", "director:20261102", "/api/chat")):
            with self.subTest(backend=backend):
                proc, out = self.run_client(backend, model)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(out.read_text(encoding="utf-8"), "Director answer.")
                self.assertNotIn("private scratch", proc.stdout)
                path, body = LocalDirectorServer.seen[-1]
                self.assertEqual(path, endpoint)
                self.assertEqual(body["model"], model)
                self.assertEqual(body["messages"][0], {"role": "system", "content": profile["system"]})

    def test_model_substitution_is_refused_before_request(self):
        proc, out = self.run_client("ollama", "director:latest")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("does not match the pinned profile", proc.stderr)
        self.assertFalse(out.exists())

    def test_registry_routes_and_loopback_inventory(self):
        self.assertEqual(providers._local_models(f"http://127.0.0.1:{self.port}/v1/models", "data"),
                         ["director-20261102"])
        self.assertEqual(providers._local_models(f"http://127.0.0.1:{self.port}/api/tags", "models"),
                         ["director:20261102"])
        for rid, model in providers.DIRECTOR_MODELS.items():
            with self.subTest(route=rid):
                route = {"state": "READY_LOCAL", "supported_modes": ["chat"]}
                self.assertTrue(providers.usable(route, "chat"))
                self.assertFalse(providers.usable(route, "agent"))
                argv = providers.build_argv(rid, "chat", "C:/project", "out", model=model)
                self.assertEqual(argv[-3:], [rid.removeprefix("director-"), model, "out"])
                with self.assertRaises(RuntimeError):
                    providers.build_argv(rid, "chat", "C:/project", "out", model="wrong")
        self.assertIn("Director (local)", lanes.DOCUMENTED_EXAMPLE)
        self.assertTrue(any(row[0] == "director-local" for row in lanes.CATALOG))


if __name__ == "__main__":
    unittest.main()
