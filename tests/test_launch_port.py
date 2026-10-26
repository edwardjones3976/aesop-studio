"""Server binding: a port another program listens on is refused (not shared), and Studio moves to the next one."""
import os
import shutil
import socket
import tempfile
import unittest
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

os.environ["AESOP_SIMULATED_ROUTE"] = "1"
os.environ["AESOP_PROBE_OFFLINE"] = "1"

from aesop_studio.server import PortUnavailableError, make_server  # noqa: E402


class TestPortClaim(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-port-"))
        # A squatter like the stray `python -m http.server` seen 2026-10-26 (HTTPServer sets SO_REUSEADDR).
        self.squat = HTTPServer(("127.0.0.1", 0), SimpleHTTPRequestHandler)
        self.port = self.squat.server_address[1]

    def tearDown(self):
        self.squat.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_busy_port_is_refused_not_shared(self):
        with self.assertRaises(PortUnavailableError):
            make_server(str(self.tmp / "a"), self.port, tries=1)

    def test_busy_port_moves_to_the_next_free_one(self):
        nxt = self.port + 1
        probe = socket.socket()
        try:
            probe.bind(("127.0.0.1", nxt))
        except OSError:
            self.skipTest(f"port {nxt} is in use on this machine")
        finally:
            probe.close()
        srv = make_server(str(self.tmp / "b"), self.port, tries=2)
        try:
            self.assertEqual(srv.server_address[1], nxt)
            self.assertEqual(srv.app.port, nxt)
            self.assertIn(f"127.0.0.1:{nxt}", srv.app.allowed_hosts())
        finally:
            srv.server_close()
            srv.app._instance_lock.close()

    def test_refused_bind_releases_the_data_dir_lock(self):
        with self.assertRaises(PortUnavailableError):
            make_server(str(self.tmp / "c"), self.port, tries=1)
        self.squat.server_close()
        srv = make_server(str(self.tmp / "c"), self.port, tries=1)  # same data dir: lock must be free again
        srv.server_close()
        srv.app._instance_lock.close()


if __name__ == "__main__":
    unittest.main()
