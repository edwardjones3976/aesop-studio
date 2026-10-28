"""Front-end Verify list must match server LIVE_VERIFY_ROUTES."""

import json
import re
import unittest
from pathlib import Path

from aesop_studio import providers

APP_JS = Path(__file__).resolve().parent.parent / "static" / "app.js"


def _verifiable_from_app_js() -> list[str]:
    text = APP_JS.read_text(encoding="utf-8")
    m = re.search(r"const VERIFIABLE = (\[[^\]]+\]);", text)
    if not m:
        raise AssertionError("VERIFIABLE constant not found in static/app.js")
    return json.loads(m.group(1))


class TestVerifyUiParity(unittest.TestCase):
    def test_verifiable_matches_live_verify_routes(self):
        front = set(_verifiable_from_app_js())
        server = set(providers.LIVE_VERIFY_ROUTES)
        self.assertEqual(front, server)


if __name__ == "__main__":
    unittest.main()
