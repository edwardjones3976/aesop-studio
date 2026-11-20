"""Owner decision 2026-11-11: Copilot is not part of Studio. No route, no lane, no command line, no Verify entry."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("AESOP_PROBE_OFFLINE", "1")

from aesop_studio import lanes, providers
from aesop_studio.store import Store

ROOT = Path(__file__).resolve().parent.parent
_RETIRED_FILTER = 'RETIRED_FROM_SECRET_DISCOVERY = frozenset({"copilot", "grok", "xai", "zai"})'


class NoCopilot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = Store(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_route_is_probed_or_named(self):
        self.assertNotIn("copilot", providers.probe(self.store))
        self.assertNotIn("copilot", providers.LIVE_VERIFY_ROUTES)
        self.assertNotIn("copilot", providers.DISPLAY)
        self.assertFalse(hasattr(providers, "_copilot_cmd"))

    def test_no_command_line_can_be_built(self):
        with self.assertRaises(RuntimeError):
            providers.build_argv("copilot", "chat", self.tmp.name, str(Path(self.tmp.name) / "last.txt"))

    def test_no_lane_is_listed(self):
        self.assertNotIn("copilot", [row[0] for row in lanes.CATALOG])
        self.assertFalse(any("copilot" in name.lower() for name in lanes.DOCUMENTED_EXAMPLE))
        found = lanes.discover(self.store)["lanes"]
        self.assertFalse([lane["id"] for lane in found if "copilot" in lane["id"].lower()])

    def test_registered_secret_file_does_not_surface_a_lane(self):
        """A leftover copilot.dpapi name must not become secret:copilot; the file is never deleted."""
        self.assertIn("copilot", lanes.RETIRED_FROM_SECRET_DISCOVERY)
        with mock.patch.object(lanes, "_secret_store_names", return_value=["copilot", "other-vendor"]):
            found = lanes.discover(self.store)["lanes"]
        ids = [lane["id"] for lane in found]
        self.assertNotIn("secret:copilot", ids)
        self.assertNotIn("copilot", [lane["id"] for lane in found])
        self.assertIn("secret:other-vendor", ids)

    def test_page_and_package_do_not_mention_it(self):
        for path in [ROOT / "static" / "app.js", *sorted((ROOT / "aesop_studio").glob("*.py"))]:
            text = path.read_text(encoding="utf-8")
            if path.name == "lanes.py":
                self.assertIn(_RETIRED_FILTER, text)
                stripped = text.replace(_RETIRED_FILTER, "")
                self.assertNotIn("copilot", stripped.lower(), path.name)
                continue
            self.assertNotIn("copilot", text.lower(), path.name)


if __name__ == "__main__":
    unittest.main()
