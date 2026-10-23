"""Owner deletions: conversations and roundtable sessions, including derived copies."""
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

os.environ["AESOP_SIMULATED_ROUTE"] = "1"
os.environ["AESOP_PROBE_OFFLINE"] = "1"

from aesop_studio import deletion, providers, roundtable  # noqa: E402
from aesop_studio.roundtable_live import ensure_schema  # noqa: E402
from aesop_studio.services import Services  # noqa: E402
from aesop_studio.store import Store  # noqa: E402
from aesop_studio.tasks import TERMINAL, Supervisor  # noqa: E402


class TestDeletion(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-del-"))
        (self.tmp / "p").mkdir()
        self.store = Store(self.tmp / "d")
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        providers.refresh(self.store)
        self.p = self.svc.create_project("P", str(self.tmp / "p"), "simulated")

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_delete_conversation_scrubs_requests(self):
        c = self.svc.new_conversation(self.p["id"])
        r = self.svc.send(self.p["id"], c["id"], "private question about widgets", [], None)
        end = time.time() + 20
        while self.sup.get(r["task_id"])["state"] not in TERMINAL and time.time() < end:
            time.sleep(0.1)
        out = deletion.delete_conversation(self.store, self.svc, self.p["id"], c["id"])
        self.assertEqual(out["messages"], 2)
        self.assertFalse(self.store.q("SELECT * FROM messages WHERE conversation_id=?", (c["id"],)))
        t = self.sup.get(r["task_id"])
        self.assertEqual(t["prompt"], "[deleted by owner]")
        self.assertNotIn("widgets", t["checkpoint"])
        self.assertFalse(os.path.exists(t["output_path"]))

    def test_delete_roundtable(self):
        ensure_schema(self.store)
        rec = roundtable.save(self.store, self.p["id"], {"mode": "general", "objective": "a long enough objective",
                                                          "deliverable": "memo", "roster": ["openai"], "sharing_ack": True})
        self.store.x("INSERT INTO roundtable_events(rt_id,event_id,kind,content,created) VALUES(?,?,?,?,?)",
                     (rec["id"], "ev_x", "message", "hello", time.time()))
        out = deletion.delete_roundtable(self.store, rec["id"])
        self.assertEqual(out["events"], 1)
        self.assertIsNone(roundtable.get(self.store, rec["id"]))
        with self.assertRaises(KeyError):
            deletion.delete_roundtable(self.store, rec["id"])


if __name__ == "__main__":
    unittest.main()
