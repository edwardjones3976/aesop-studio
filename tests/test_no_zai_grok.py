"""Owner decision 2026-11-19 (AS-24): Z.ai and Grok leave Studio indefinitely.

No route, no lane, no command line, no Verify entry. Leftover *.dpapi names stay archived.
"""
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
_RETIRED = ("grok", "zai")


class NoZaiGrok(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = Store(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_route_is_probed_or_named(self):
        probed = providers.probe(self.store)
        for rid in _RETIRED:
            self.assertNotIn(rid, probed)
            self.assertNotIn(rid, providers.LIVE_VERIFY_ROUTES)
            self.assertNotIn(rid, providers.DISPLAY)
            self.assertNotIn(rid, providers.AUTO_REVERIFY_ROUTES)
            self.assertFalse(hasattr(providers, f"_{rid}_cmd"))

    def test_no_command_line_can_be_built(self):
        for rid in _RETIRED:
            with self.subTest(route=rid), self.assertRaises(RuntimeError):
                providers.build_argv(rid, "chat", self.tmp.name, str(Path(self.tmp.name) / "last.txt"),
                                     prompt="hi")

    def test_no_lane_is_listed(self):
        catalog_ids = [row[0] for row in lanes.CATALOG]
        for rid in _RETIRED:
            self.assertNotIn(rid, catalog_ids)
        example = " ".join(lanes.DOCUMENTED_EXAMPLE).lower()
        self.assertNotIn("grok", example)
        self.assertNotIn("z.ai", example)
        self.assertNotIn("zai", example)
        found = lanes.discover(self.store)["lanes"]
        for rid in _RETIRED:
            self.assertFalse([lane["id"] for lane in found if rid in lane["id"].lower()])

    def test_registered_secret_file_does_not_surface_a_lane(self):
        """Leftover zai/grok/xai.dpapi names must not become secret:* lanes; files are never deleted."""
        for name in ("grok", "zai", "xai"):
            self.assertIn(name, lanes.RETIRED_FROM_SECRET_DISCOVERY)
        with mock.patch.object(lanes, "_secret_store_names",
                               return_value=["grok", "zai", "xai", "other-vendor"]):
            found = lanes.discover(self.store)["lanes"]
        ids = [lane["id"] for lane in found]
        for name in ("grok", "zai", "xai"):
            self.assertNotIn(f"secret:{name}", ids)
            self.assertNotIn(name, [lane["id"] for lane in found])
        self.assertIn("secret:other-vendor", ids)

    def test_page_and_package_do_not_mention_them(self):
        for path in [ROOT / "static" / "app.js", *sorted((ROOT / "aesop_studio").glob("*.py"))]:
            text = path.read_text(encoding="utf-8")
            if path.name == "lanes.py":
                self.assertIn(_RETIRED_FILTER, text)
                stripped = text.replace(_RETIRED_FILTER, "")
                for token in ("grok", "zai", "z.ai"):
                    self.assertNotIn(token, stripped.lower(), path.name)
                continue
            low = text.lower()
            for token in ("grok", "zai", "z.ai", "claude-zai"):
                self.assertNotIn(token, low, path.name)


if __name__ == "__main__":
    unittest.main()
