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

# Windows Hyper-V / HTTP.sys excluded ranges return WinError 10013 on exclusive bind.
# Probe with the same SO_EXCLUSIVEADDRUSE Studio uses, and allow fall-forward past holes.
_SCAN = 32


def _exclusive_bind_ok(port: int) -> bool:
    """True if Studio's exclusive loopback claim would succeed on this port right now."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


@unittest.skipUnless(os.name == "nt", "exclusive loopback port bind (SO_EXCLUSIVEADDRUSE) is Windows-only")
class TestPortClaim(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-port-"))
        # A squatter like the stray `python -m http.server` seen 2026-10-26 (HTTPServer sets SO_REUSEADDR).
        self.squat = HTTPServer(("127.0.0.1", 0), SimpleHTTPRequestHandler)
        self.port = self.squat.server_address[1]

    def tearDown(self):
        self.squat.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _respawn_squatter(self):
        self.squat.server_close()
        self.squat = HTTPServer(("127.0.0.1", 0), SimpleHTTPRequestHandler)
        self.port = self.squat.server_address[1]

    def test_busy_port_is_refused_not_shared(self):
        with self.assertRaises(PortUnavailableError):
            make_server(str(self.tmp / "a"), self.port, tries=1)

    def test_busy_port_moves_to_the_next_free_one(self):
        # A plain bind() probe is not enough: Windows excluded ports can look free until SO_EXCLUSIVEADDRUSE
        # (CI 2026-11-20 windows-latest: neighbour → "forbidden by its access permissions").
        for _ in range(64):
            expected = None
            for candidate in range(self.port + 1, self.port + _SCAN):
                if _exclusive_bind_ok(candidate):
                    expected = candidate
                    break
            if expected is None:
                self._respawn_squatter()
                continue
            try:
                srv = make_server(str(self.tmp / "b"), self.port, tries=_SCAN)
            except PortUnavailableError:
                self._respawn_squatter()
                continue
            try:
                if srv.server_address[1] != expected:
                    # Exclusion map or another listener moved between probe and claim; try a new pair.
                    self._respawn_squatter()
                    continue
                self.assertEqual(srv.app.port, expected)
                self.assertIn(f"127.0.0.1:{expected}", srv.app.allowed_hosts())
                return
            finally:
                srv.server_close()
                srv.app._instance_lock.close()
        self.skipTest("could not claim the next exclusive-free port near a squatter")

    def test_refused_bind_releases_the_data_dir_lock(self):
        with self.assertRaises(PortUnavailableError):
            make_server(str(self.tmp / "c"), self.port, tries=1)
        self.squat.server_close()
        srv = make_server(str(self.tmp / "c"), self.port, tries=1)  # same data dir: lock must be free again
        srv.server_close()
        srv.app._instance_lock.close()


if __name__ == "__main__":
    unittest.main()
