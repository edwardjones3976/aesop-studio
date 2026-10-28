"""Build + review: one automatic review per build, owner-gated fixes, bounded rounds (simulated routes)."""

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

os.environ["AESOP_SIMULATED_ROUTE"] = "1"
os.environ["AESOP_PROBE_OFFLINE"] = "1"

from aesop_studio import providers, team  # noqa: E402
from aesop_studio.services import Services  # noqa: E402
from aesop_studio.store import Store  # noqa: E402
from aesop_studio.tasks import TERMINAL, Supervisor  # noqa: E402


class TestTeam(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-team-"))
        self.root = self.tmp / "p"
        self.root.mkdir()
        (self.root / "app.py").write_text("print('v1')\n", encoding="utf-8")
        self.git = shutil.which("git") is not None
        if self.git:
            for cmd in (
                ["init", "-q"],
                ["add", "."],
                ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "v1"],
            ):
                subprocess.run(
                    ["git", "-C", str(self.root)] + cmd, check=True, capture_output=True
                )
        self.store = Store(self.tmp / "d")
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        providers.refresh(self.store)
        self.p = self.svc.create_project("P", str(self.root), "simulated")
        self.store.x(
            "INSERT INTO kv(k,v) VALUES(?, 'on')", (f"agent_ack:{self.p['id']}",)
        )

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def wait_review(self, tid, states=("DONE", "FAILED", "SKIPPED", "BLOCKED")):
        end = time.time() + 40
        while time.time() < end:
            r = team.get(self.store, tid)
            if r and r["state"] in states:
                return r
            time.sleep(0.2)
        return team.get(self.store, tid)

    def test_parse_is_strict(self):
        r = team._parse(
            'ok {"verdict": "approve", "summary": "s", "issues": [{"file": "a.py", "line": 3, "severity": "high", "problem": "p", "fix": "f"}]}'
        )
        self.assertEqual(
            r["verdict"], "changes"
        )  # approve with a high issue is not an approval
        self.assertEqual(r["issues"][0]["line"], 3)
        self.assertEqual(team._parse("no json")["verdict"], "unclear")

    def test_review_after_build_then_owner_fixes_and_round_cap(self):
        self.svc.update_project(self.p["id"], {"transfer_policy": {"simulated": False}})
        tid = self.sup.create(
            self.p, "simulated", "WRITE a new file", mode="agent", timeout=30
        )
        team.plan(self.store, tid, "simulated")
        team.watch(self.store, self.sup, self.svc, tid)
        r = self.wait_review(tid)
        self.assertEqual(
            r["state"], "BLOCKED"
        )  # sending project files to the reviewer is off by default
        self.svc.update_project(self.p["id"], {"transfer_policy": {"simulated": True}})
        team.retry(self.store, self.sup, self.svc, tid)
        r = self.wait_review(tid)
        self.assertEqual(r["state"], "DONE", r)
        prompt = self.sup.get(r["review_task"])["prompt"]
        self.assertIn("WRITE a new file", prompt)
        if self.git:
            self.assertIn("git diff", r["change_kind"])
            self.assertIn(
                "sim_output.txt", prompt
            )  # the untracked file the builder created
        self.assertEqual(
            r["verdict"], "unclear"
        )  # the simulated reviewer does not answer in JSON
        self.assertIsNone(r.get("fix_task"))  # nothing is sent back on its own
        with self.assertRaises(ValueError):
            team.send_fixes(self.store, self.sup, self.svc, tid, [], "")
        # owner sends fixes: a new agent task for the same builder, reviewed again as round 2
        r["issues"] = [
            {
                "file": "sim_output.txt",
                "line": None,
                "severity": "medium",
                "problem": "typo",
                "fix": "fix it",
            }
        ]
        team._put(self.store, tid, r)
        out = team.send_fixes(self.store, self.sup, self.svc, tid, [0], "please")
        fix = out["task"]["id"]
        self.assertIn("typo", self.sup.get(fix)["prompt"])
        self.assertEqual(team.get(self.store, fix)["round"], 2)
        r2 = self.wait_review(fix)
        self.assertEqual(r2["state"], "DONE")
        r2["round"] = team.MAX_ROUNDS
        r2["issues"] = r["issues"]
        team._put(self.store, fix, r2)
        with self.assertRaises(ValueError):  # bounded: no endless model-to-model loop
            team.send_fixes(self.store, self.sup, self.svc, fix, [0])
        self.assertTrue(team.accept(self.store, fix)["accepted_at"])

    def test_failed_build_is_not_reviewed_and_resume_after_restart(self):
        self.svc.update_project(self.p["id"], {"transfer_policy": {"simulated": True}})
        bad = self.sup.create(self.p, "simulated", "FAIL now", mode="agent", timeout=30)
        team.plan(self.store, bad, "simulated")
        team.watch(self.store, self.sup, self.svc, bad)
        self.assertEqual(self.wait_review(bad)["state"], "SKIPPED")
        # a plan that was waiting when Studio stopped is picked up again
        tid = self.sup.create(
            self.p, "simulated", "WRITE again", mode="agent", timeout=30
        )
        team.plan(self.store, tid, "simulated")
        self.assertEqual(team.resume(self.store, self.sup, self.svc), 1)
        self.assertEqual(self.wait_review(tid)["state"], "DONE")
        self.assertNotIn(
            "simulated", team.reviewers(self.store, "simulated")
        )  # never reviews its own work


if __name__ == "__main__":
    unittest.main()


class TestBuildTests(TestTeam):
    def test_tests_run_after_build_and_reach_the_reviewer(self):
        (self.root / "calc.py").write_text(
            "def add(a, b):\n    return a + b\n", encoding="utf-8"
        )
        (self.root / "test_calc.py").write_text(
            "import unittest\nfrom calc import add\n\nclass T(unittest.TestCase):\n"
            "    def test_add(self):\n        self.assertEqual(add(2, 2), 4)\n\n"
            "    def test_env_has_no_keys(self):\n        import os\n"
            "        self.assertFalse([k for k in os.environ if 'KEY' in k.upper() or 'TOKEN' in k.upper()])\n",
            encoding="utf-8",
        )
        os.environ["AESOP_FAKE_API_KEY"] = "must-not-leak"
        try:
            self.svc.update_project(
                self.p["id"], {"transfer_policy": {"simulated": True}}
            )
            tid = self.sup.create(
                self.p, "simulated", "WRITE something", mode="agent", timeout=30
            )
            team.plan(self.store, tid, "simulated")
            team.watch(self.store, self.sup, self.svc, tid)
            r = self.wait_review(tid)
        finally:
            os.environ.pop("AESOP_FAKE_API_KEY", None)
        self.assertEqual(r["tests"]["state"], "PASSED", r["tests"])
        self.assertEqual(r["tests"]["summary"], "all 2 passed")
        self.assertIn("Tests, run by Studio", self.sup.get(r["review_task"])["prompt"])
        # a failing test is reported as FAILED with the count, and no reviewer is needed for tests to run
        (self.root / "test_calc.py").write_text(
            "import unittest\n\nclass T(unittest.TestCase):\n    def test_bad(self):\n        self.assertEqual(1, 2)\n",
            encoding="utf-8",
        )
        tid2 = self.sup.create(
            self.p, "simulated", "WRITE more", mode="agent", timeout=30
        )
        team.plan(self.store, tid2, None)
        team.watch(self.store, self.sup, self.svc, tid2)
        end = time.time() + 60
        while time.time() < end and (
            team.get(self.store, tid2)["tests"]["state"] in ("WAITING", "RUNNING")
        ):
            time.sleep(0.2)
        t2 = team.get(self.store, tid2)["tests"]
        self.assertEqual(t2["state"], "FAILED")
        self.assertEqual(t2["summary"], "0 of 1 passed")

    def test_no_tests_found(self):
        from aesop_studio import testrun

        self.assertEqual(testrun.run(str(self.tmp / "d"))["state"], "NO_TESTS")
