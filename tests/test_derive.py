"""Model-assisted proposals: draft findings and conversation summaries stay proposed until accepted."""
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

os.environ["AESOP_SIMULATED_ROUTE"] = "1"
os.environ["AESOP_PROBE_OFFLINE"] = "1"

from aesop_studio import derive, providers  # noqa: E402
from aesop_studio.services import Conflict, Services  # noqa: E402
from aesop_studio.store import Store  # noqa: E402
from aesop_studio.tasks import Supervisor  # noqa: E402


class TestDerive(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-drv-"))
        (self.tmp / "p").mkdir()
        self.store = Store(self.tmp / "d")
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        providers.refresh(self.store)
        self.p = self.svc.create_project("P", str(self.tmp / "p"), "simulated")

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def wait(self, did):
        end = time.time() + 20
        while time.time() < end:
            d = derive.get(self.store, self.svc, self.sup, did)
            if d["status"] != "RUNNING":
                return d
            time.sleep(0.1)
        raise AssertionError("derivation stuck")

    def test_draft_findings_are_proposals_with_valid_citations_only(self):
        a = self.svc.attach(self.p["id"], "study.txt", b"Synthetic study: widgets improved 3%.")
        src = self.svc.add_local_source(self.p["id"], a["id"])
        with self.assertRaises(PermissionError):  # private local doc needs the transfer permission
            derive.draft_findings(self.store, self.svc, self.sup, self.p["id"], [src["id"]])
        self.svc.update_project(self.p["id"], {"transfer_policy": {"simulated": True}})
        d = self.wait(derive.draft_findings(self.store, self.svc, self.sup, self.p["id"], [src["id"]])["id"])
        self.assertEqual(d["status"], "DONE")
        self.assertEqual(len(d["result"]["created"]), 1)
        self.assertEqual(d["result"]["rejected"][0]["why"], "cites a source outside this job")
        fid = d["result"]["created"][0]
        f = self.store.one("SELECT * FROM findings WHERE id=?", (fid,))
        self.assertEqual(f["status"], "proposed")
        self.assertNotIn("widgets improved", self.svc.export_notebook(self.p["id"], include_private=True))
        self.assertEqual(derive.decide_finding(self.store, self.p["id"], fid, True)["status"], "cited")
        self.assertIn("widgets improved", self.svc.export_notebook(self.p["id"], include_private=True))
        with self.assertRaises(ValueError):
            derive.decide_finding(self.store, self.p["id"], fid, False)  # already decided

    def test_summary_is_proposed_derived_memory_citing_real_messages(self):
        c = self.svc.new_conversation(self.p["id"])
        r = self.svc.send(self.p["id"], c["id"], "Which store for notes?", [], None)
        end = time.time() + 20
        while self.sup.get(r["task_id"])["state"] not in ("COMPLETED", "FAILED") and time.time() < end:
            time.sleep(0.1)
        self.svc.messages(self.p["id"], c["id"])
        d = self.wait(derive.summarize_conversation(self.store, self.svc, self.sup, self.p["id"], c["id"])["id"])
        self.assertEqual(d["status"], "DONE")
        m = self.store.one("SELECT * FROM memory WHERE id=?", (d["result"]["created"][0],))
        self.assertEqual((m["layer"], m["status"]), ("derived", "proposed"))
        self.assertNotIn("msg_bogus", m["source_ids"])
        self.assertFalse(any(x["id"] == m["id"] for x in self.svc.context_packet(self.p["id"])["current_memory"]))
        derive.decide_memory(self.store, self.p["id"], m["id"], True)
        self.assertTrue(any(x["id"] == m["id"] for x in self.svc.context_packet(self.p["id"])["current_memory"]))

    def test_explicit_switch_required_and_unread_sources_refused(self):
        src = self.svc.add_public_source(self.p["id"], "http://127.0.0.1/")  # blocked -> unavailable
        with self.assertRaises(ValueError):
            derive.draft_findings(self.store, self.svc, self.sup, self.p["id"], [src["id"]])
        with self.assertRaises(Conflict):
            derive.draft_findings(self.store, self.svc, self.sup, self.p["id"], [src["id"]], provider="codex")


if __name__ == "__main__":
    unittest.main()
