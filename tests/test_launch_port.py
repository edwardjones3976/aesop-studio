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
_MAX_PORT = 65535


def _exclusive_bind_ok(port: int) -> bool:
    """True if Studio's exclusive loopback claim would succeed on this port right now."""
    if port < 0 or port > _MAX_PORT:
        return False
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind(("127.0.0.1", port))
        return True
    except (OSError, OverflowError):
        return False
    finally:
        probe.close()


def _hold_exclusive(port: int) -> socket.socket:
    """Bind and keep an exclusive socket so the port stays unusable to Studio."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(1)
    return sock


def _scan_stop(start: int, span: int = _SCAN) -> int:
    """Exclusive end of a probe/claim window that never exceeds TCP port 65535."""
    return min(start + max(1, span), _MAX_PORT + 1)


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
            if self.port >= _MAX_PORT:
                self._respawn_squatter()
                continue
            stop = _scan_stop(self.port + 1)
            expected = None
            for candidate in range(self.port + 1, stop):
                if _exclusive_bind_ok(candidate):
                    expected = candidate
                    break
            if expected is None:
                self._respawn_squatter()
                continue
            tries = stop - self.port
            try:
                srv = make_server(str(self.tmp / "b"), self.port, tries=tries)
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

    def test_make_server_falls_forward_past_two_held_ports(self):
        # Hold P and P+1 exclusively; make_server(P, tries=3) must land on P+2.
        # Windows Hyper-V / HTTP.sys can flip P+2 to WinError 10013 between the probe and the
        # claim (CI push run 44655379005 on tip 82f304b); retry a fresh trio instead of failing.
        holders = []
        try:
            for _ in range(64):
                for h in holders:
                    h.close()
                holders = []
                probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    probe.bind(("127.0.0.1", 0))
                    start = probe.getsockname()[1]
                finally:
                    probe.close()
                if start > _MAX_PORT - 2:
                    continue
                if not all(_exclusive_bind_ok(start + i) for i in (0, 1, 2)):
                    continue
                try:
                    holders.append(_hold_exclusive(start))
                    holders.append(_hold_exclusive(start + 1))
                except OSError:
                    for h in holders:
                        h.close()
                    holders = []
                    continue
                # Re-check after holding: exclusion can appear once neighbours are claimed.
                if not _exclusive_bind_ok(start + 2):
                    continue
                try:
                    srv = make_server(str(self.tmp / "d"), start, tries=3)
                except PortUnavailableError:
                    continue
                try:
                    if srv.server_address[1] != start + 2:
                        continue
                    self.assertEqual(srv.app.port, start + 2)
                    self.assertIn(f"127.0.0.1:{start + 2}", srv.app.allowed_hosts())
                    return
                finally:
                    srv.server_close()
                    srv.app._instance_lock.close()
            self.skipTest("could not reserve three consecutive exclusive-free ports")
        finally:
            for h in holders:
                h.close()

    def test_refused_bind_releases_the_data_dir_lock(self):
        with self.assertRaises(PortUnavailableError):
            make_server(str(self.tmp / "c"), self.port, tries=1)
        self.squat.server_close()
        srv = make_server(str(self.tmp / "c"), self.port, tries=1)  # same data dir: lock must be free again
        srv.server_close()
        srv.app._instance_lock.close()


if __name__ == "__main__":
    unittest.main()
