"""SQLite store: authoritative local records for every Aesop Studio project."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, root TEXT NOT NULL, provider_default TEXT,
  model TEXT, transfer_policy TEXT NOT NULL DEFAULT '{}', retention_days INTEGER NOT NULL DEFAULT 90,
  created REAL NOT NULL, updated REAL NOT NULL, archived INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS conversations(
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), title TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS messages(
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id), role TEXT NOT NULL,
  content TEXT NOT NULL, status TEXT NOT NULL, provider TEXT, created REAL NOT NULL, meta TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS attachments(
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), name TEXT NOT NULL, sha256 TEXT NOT NULL,
  size INTEGER NOT NULL, stored_path TEXT NOT NULL, extract_status TEXT NOT NULL, extract_text TEXT,
  extract_note TEXT, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS artifacts(
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), kind TEXT NOT NULL, title TEXT NOT NULL,
  content TEXT NOT NULL, source_ref TEXT, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS tasks(
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), provider TEXT NOT NULL, prompt TEXT NOT NULL,
  state TEXT NOT NULL, pid INTEGER, cwd TEXT, argv_meta TEXT, exit_code INTEGER, output_path TEXT,
  reservation_usd REAL NOT NULL DEFAULT 0, checkpoint TEXT, changed_files TEXT, error TEXT,
  created REAL NOT NULL, started REAL, ended REAL);
CREATE TABLE IF NOT EXISTS sources(
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), kind TEXT NOT NULL, title TEXT NOT NULL,
  publisher TEXT, locator TEXT NOT NULL, retrieved_at REAL, version TEXT, status TEXT NOT NULL,
  excerpt TEXT, private INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS findings(
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), claim TEXT NOT NULL,
  source_id TEXT REFERENCES sources(id), locator TEXT, status TEXT NOT NULL, limitation TEXT, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS memory(
  id TEXT PRIMARY KEY, project_id TEXT, layer TEXT NOT NULL, kind TEXT NOT NULL, content TEXT NOT NULL,
  source_ids TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL, superseded_by TEXT, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ledger(
  id TEXT PRIMARY KEY, provider TEXT NOT NULL, route TEXT NOT NULL, billing_basis TEXT NOT NULL,
  task_ref TEXT, reservation_usd REAL NOT NULL, settled_usd REAL, status TEXT NOT NULL,
  price_source TEXT, created REAL NOT NULL, settled REAL, purpose TEXT NOT NULL DEFAULT 'mission');
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, project_id TEXT, data TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS repairs(
  id TEXT PRIMARY KEY, task_id TEXT, signature TEXT NOT NULL, reproducer TEXT, contract TEXT,
  status TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Store:
    def __init__(self, data_dir: str | os.PathLike):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "files").mkdir(exist_ok=True)
        (self.data_dir / "task-output").mkdir(exist_ok=True)
        self.path = self.data_dir / "aesop.db"
        self._local = threading.local()
        self.write_lock = threading.RLock()
        with self.conn() as c:
            c.executescript(SCHEMA)
            cols = {r[1] for r in c.execute("PRAGMA table_info(ledger)")}
            if "purpose" not in cols:  # migrate stores created before the runtime envelope existed
                c.execute("ALTER TABLE ledger ADD COLUMN purpose TEXT NOT NULL DEFAULT 'mission'")
                c.execute("UPDATE ledger SET purpose='included' WHERE billing_basis='subscription_included'")

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        return c

    @contextmanager
    def conn(self):
        c = getattr(self._local, "c", None)
        if c is None:
            c = self._local.c = self._connect()
        yield c

    @contextmanager
    def tx(self):
        """Serialized write transaction (BEGIN IMMEDIATE) for atomic check-then-write."""
        with self.write_lock, self.conn() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise

    def q(self, sql: str, args=()) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    def one(self, sql: str, args=()) -> dict | None:
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def x(self, sql: str, args=()) -> None:
        with self.tx() as c:
            c.execute(sql, args)

    def event(self, kind: str, project_id: str | None, /, **data) -> None:  # positional-only: data may use "kind"
        self.x("INSERT INTO events(kind,project_id,data,created) VALUES(?,?,?,?)",
               (kind, project_id, json.dumps(data), time.time()))

    def close(self) -> None:
        c = getattr(self._local, "c", None)
        if c is not None:
            c.close()
            self._local.c = None
