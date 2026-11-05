# [[OpenAI Codex | GPT-5.6-sol | 2026-11-05 | 04:23 UTC | BEGIN]]
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
from unittest import mock

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
        if self.path == "/api/show":
            data = {"modelfile": "FROM C:\\\\models\\\\blobs\\\\sha256-baab9ccb424b607ad70aebdcbaeb2337a6eecd6a7e0fc9c6dc7569c72f9588bc"}
        else:
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
        cls.server.server_close()

    def run_client(self, backend: str, model: str, prompt: str = "Question?"):
        out = Path(tempfile.mkdtemp()) / "answer.txt"
        env = dict(os.environ, **{f"AESOP_{backend.upper()}_PORT": str(self.port)})
        proc = subprocess.run([sys.executable, "-I", str(CLIENT), backend, model, str(out)], input=prompt,
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

    def test_oversized_input_is_refused_before_request(self):
        before = len(LocalDirectorServer.seen)
        proc, out = self.run_client("ollama", "director:20261102", "x" * 7000)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("exceeds the local Director context contract", proc.stderr)
        self.assertFalse(out.exists())
        self.assertEqual(len(LocalDirectorServer.seen), before)

    def test_registry_routes_and_loopback_inventory(self):
        self.assertEqual(providers._local_models(f"http://127.0.0.1:{self.port}/v1/models", "data"),
                         ["director-20261102"])
        self.assertEqual(providers._local_models(f"http://127.0.0.1:{self.port}/api/tags", "models"),
                         ["director:20261102"])
        for rid, model in providers.director_models().items():
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

    def test_runtime_bindings_fail_closed_on_artifact_substitution(self):
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td:
            artifact = Path(td) / "director.gguf"
            artifact.write_bytes(b"exact")
            stat = artifact.stat()
            binding = {"artifact_path": str(artifact), "catalog_path": "Director/director.gguf",
                       "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                       "sha256": profile["gguf_sha256"]}
            catalog = json.dumps([{"modelKey": "director-20261102", "path": "Director/director.gguf",
                                   "sizeBytes": stat.st_size}])
            with mock.patch.object(providers.shutil, "which", return_value="lms.exe"), \
                    mock.patch.object(providers, "_run", return_value=(0, catalog)):
                self.assertTrue(providers._lmstudio_binding("director-20261102", binding)[0])
                artifact.write_bytes(b"changed")
                self.assertFalse(providers._lmstudio_binding("director-20261102", binding)[0])
        with mock.patch.dict(os.environ, {"AESOP_OLLAMA_PORT": str(self.port)}):
            self.assertTrue(providers._ollama_binding("director:20261102", profile["bindings"]["ollama"])[0])
            bad = {"blob_sha256": "0" * 64}
            self.assertFalse(providers._ollama_binding("director:20261102", bad)[0])


if __name__ == "__main__":
    unittest.main()
# [[OpenAI Codex | GPT-5.6-sol | 2026-11-05 | 04:23 UTC | END]]
