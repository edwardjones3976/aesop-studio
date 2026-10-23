"""Persistent browser sessions for the loopback Studio server.

A session survives server restarts and browser restarts for SESSION_DAYS (sliding: every use renews it).
Only SHA-256 fingerprints of the session cookie and the origin key are written to disk, so the file alone
cannot be replayed as a login. The CSRF token is kept as-is (it is useless without the cookie and key).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

SESSION_DAYS = 30
_SAVE_EVERY_S = 300  # renewals are written at most this often (each new login is written immediately)


def _h(v: str) -> str:
    return hashlib.sha256(v.encode("utf-8")).hexdigest()


class Sessions:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "sessions.json"
        self.lock = threading.Lock()
        self.items: dict[str, dict] = {}
        self._saved = 0.0
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            now = time.time()
            self.items = {k: v for k, v in raw.items() if v.get("expires", 0) > now}
        except (OSError, ValueError):
            self.items = {}

    def _save(self, force: bool = False) -> None:
        if not force and time.time() - self._saved < _SAVE_EVERY_S:
            return
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.items), encoding="utf-8")
        os.replace(tmp, self.path)
        self._saved = time.time()

    def create(self) -> tuple[str, str, str]:
        """New session: returns (cookie value, csrf token, origin key)."""
        sess, csrf, key = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.lock:
            self.items[_h(sess)] = {"csrf": csrf, "key": _h(key), "expires": time.time() + SESSION_DAYS * 86400}
            self._save(force=True)
        return sess, csrf, key

    def get(self, sess: str | None) -> dict | None:
        if not sess:
            return None
        with self.lock:
            it = self.items.get(_h(sess))
            if not it or it["expires"] <= time.time():
                return None
            it["expires"] = time.time() + SESSION_DAYS * 86400  # sliding renewal
            self._save()
            return it

    def key_ok(self, it: dict, key: str) -> bool:
        return bool(key) and hmac.compare_digest(_h(key), it["key"])

    def revoke_all(self) -> None:
        with self.lock:
            self.items = {}
            self._save(force=True)
