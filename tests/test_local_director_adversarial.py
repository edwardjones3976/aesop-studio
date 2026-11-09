"""Adversarial checks for the exact local Director guard and its local accounting."""
from __future__ import annotations

import importlib.util
import json
import os
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from aesop_studio import ledger, local_director_client, providers
from aesop_studio.store import Store

ROOT = Path(__file__).resolve().parent.parent


def _load_cache_tool():
    spec = importlib.util.spec_from_file_location("cache_vs_source", ROOT / "tools" / "cache_vs_source.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Target(BaseHTTPRequestHandler):
    hits = 0

    def log_message(self, *_args):
        pass

    def do_GET(self):
        type(self).hits += 1
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"data": []}')

    do_POST = do_GET


class _Redirect(BaseHTTPRequestHandler):
    location = ""

    def log_message(self, *_args):
        pass

    def _send(self):
        self.send_response(302)
        self.send_header("Location", self.location)
        self.end_headers()

    do_GET = _send
    do_POST = _send


class TestLocalDirectorAdversarial(unittest.TestCase):
    def setUp(self):
        self.servers = []

    def tearDown(self):
        for server in self.servers:
            server.shutdown()
            server.server_close()

    def _server(self, handler):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.servers.append(server)
        return port

    def test_loopback_clients_refuse_redirects_without_contacting_target(self):
        _Target.hits = 0
        target_port = self._server(_Target)
        _Redirect.location = f"http://127.0.0.1:{target_port}/target"
        redirect_port = self._server(_Redirect)
        url = f"http://127.0.0.1:{redirect_port}/redirect"

        self.assertIsNone(providers._local_models(url, "data"))
        with mock.patch.dict(os.environ, {"AESOP_OLLAMA_PORT": str(redirect_port)}):
            self.assertFalse(providers._ollama_binding("director:test", {"blob_sha256": "a" * 64})[0])
        profile = {"context_tokens": 100, "max_output_tokens": 10, "input_overhead_tokens": 10,
                   "temperature": 0}
        with mock.patch.dict(os.environ, {"AESOP_LMSTUDIO_PORT": str(redirect_port)}):
            with self.assertRaises(urllib.error.HTTPError) as error:
                local_director_client._request("lmstudio", "director:test", "hello", profile, "role")
            error.exception.close()
        self.assertEqual(_Target.hits, 0)

    def test_dispatch_rechecks_the_shared_artifact_binding(self):
        model = providers.director_models()["director-lmstudio"]
        with mock.patch.object(providers, "_director_binding", return_value=(False, "changed")) as binding:
            with self.assertRaisesRegex(RuntimeError, "changed"):
                providers.build_argv("director-lmstudio", "chat", "C:/project", "out", model=model)
        binding.assert_called_once_with("director-lmstudio", model)

    def test_ollama_from_must_name_the_exact_blob(self):
        digest = "b" * 64
        self.assertFalse(providers._ollama_from_digest(f"# sha256-{digest}\nFROM wrong", digest))
        self.assertTrue(providers._ollama_from_digest(f"FROM C:\\models\\blobs\\sha256-{digest}", digest))

    def test_local_ledger_is_zero_only_and_provider_bound(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(Path(td))
            try:
                lid = ledger.reserve(store, "local", "director-lmstudio", "local", None, task_ref="task")
                ledger.settle(store, lid, 0)
                row = store.one("SELECT * FROM ledger WHERE id=?", (lid,))
                self.assertEqual((row["reservation_usd"], row["settled_usd"], row["status"]), (0, 0, "settled"))
                with self.assertRaises(ledger.BudgetError):
                    ledger.reserve(store, "openai", "director-lmstudio", "local", None)
                with self.assertRaises(ledger.BudgetError):
                    ledger.reserve(store, "local", "director-lmstudio", "local", 0.01)
            finally:
                store.close()

    def test_oversized_context_is_a_value_error(self):
        with self.assertRaises(ValueError):
            providers.validate_director_prompt("director-lmstudio", "x" * 7000)

    def test_custom_ports_drive_inventory_urls_and_labels(self):
        with mock.patch.dict(os.environ, {"AESOP_LMSTUDIO_PORT": "2234", "AESOP_OLLAMA_PORT": "2243"}):
            rows = providers._director_endpoints()
        self.assertEqual(rows[0][1:3], ("LM Studio 127.0.0.1:2234", "http://127.0.0.1:2234/v1/models"))
        self.assertEqual(rows[1][1:3], ("Ollama 127.0.0.1:2243", "http://127.0.0.1:2243/api/tags"))

    def test_cache_tool_uses_server_data_default_and_verify_projection(self):
        tool = _load_cache_tool()
        with mock.patch.dict(os.environ, {"AESOP_DATA": "C:/chosen", "LOCALAPPDATA": "C:/local"}, clear=True):
            self.assertEqual(tool.default_data_dir(), "C:/chosen")
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": "C:/local"}, clear=True):
            self.assertEqual(Path(tool.default_data_dir()), Path("C:/local/AesopStudio"))
        now = time.time()
        expected = tool.expected_verify_fields({"at": now, "ok": True, "detail": "reply matched"}, now)
        self.assertEqual(expected["state"], "READY_INCLUDED")
        self.assertEqual(expected["last_verified_at"], now)
        self.assertIn("reply matched", expected["evidence"])

    def test_stdio_is_configured_for_utf8(self):
        stdin = mock.Mock()
        stdout = mock.Mock()
        with mock.patch.object(local_director_client.sys, "stdin", stdin), \
                mock.patch.object(local_director_client.sys, "stdout", stdout):
            local_director_client._configure_utf8_stdio()
        stdin.reconfigure.assert_called_once_with(encoding="utf-8")
        stdout.reconfigure.assert_called_once_with(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
