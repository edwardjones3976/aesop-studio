"""Offline prompt generator: schema, scaffolds, variables, enhance gate."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ["AESOP_SIMULATED_ROUTE"] = "1"
os.environ["AESOP_PROBE_OFFLINE"] = "1"

from aesop_studio import prompt_generator, providers  # noqa: E402
from aesop_studio.services import Services  # noqa: E402
from aesop_studio.store import Store  # noqa: E402
from aesop_studio.tasks import Supervisor  # noqa: E402


class TestPromptGenerator(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-pg-"))
        (self.tmp / "p").mkdir()
        self.store = Store(self.tmp / "d")
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        providers.refresh(self.store)
        self.p = self.svc.create_project("P", str(self.tmp / "p"), "simulated")
        self.store.x("INSERT INTO kv(k,v) VALUES(?, 'on')", (f"agent_ack:{self.p['id']}",))

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_schema_lists_modes(self):
        s = prompt_generator.schema()
        ids = [m["id"] for m in s["modes"]]
        self.assertEqual(ids[0], "auto")
        self.assertIn("automation", ids)
        self.assertEqual({k["id"] for k in s["output_kinds"]}, {"ready", "reusable"})
        self.assertTrue(any(l["id"] == "en" for l in s["languages"]))

    def test_ready_scaffold(self):
        r = prompt_generator.generate(
            self.store, self.p["id"],
            idea="Write a launch checklist for a local studio tool",
            mode="planning",
            target="studio",
            language="en",
            output_kind="ready",
            audience="project owner",
            output_format="numbered checklist",
            constraints="no purchases",
        )
        self.assertEqual(r["mode"], "planning")
        self.assertEqual(r["spend"], "none")
        self.assertIn("Goal:", r["prompt"])
        self.assertIn("launch checklist", r["prompt"])
        self.assertIn("no purchases", r["prompt"])
        self.assertEqual(r["variables"], [])
        self.assertTrue(r["recommended_routes"])
        self.assertGreater(r["token_estimate"]["input"], 0)

    def test_reusable_variables_and_auto_mode(self):
        r = prompt_generator.generate(
            self.store, self.p["id"],
            idea="refactor the chat composer typescript module and add unit tests",
            mode="auto",
            output_kind="reusable",
        )
        self.assertEqual(r["mode"], "code")
        names = {v["name"] for v in r["variables"]}
        self.assertTrue({"goal", "audience", "constraints"} <= names)
        self.assertIn("{goal}", r["prompt"])

    def test_rejects_empty_and_bad_mode(self):
        with self.assertRaises(ValueError):
            prompt_generator.generate(self.store, self.p["id"], idea="hi")
        with self.assertRaises(ValueError):
            prompt_generator.generate(self.store, self.p["id"], idea="enough text here", mode="nope")

    def test_enhance_with_simulated(self):
        base = prompt_generator.generate(
            self.store, self.p["id"], idea="Summarize the project memory rules for a new agent",
            mode="writing", output_kind="ready",
        )
        out = prompt_generator.enhance(self.store, self.sup, self.svc, self.p["id"], base["prompt"], "simulated")
        self.assertEqual(out["spend"], "included_or_simulated")
        self.assertGreaterEqual(len(out["prompt"]), 10)
        self.assertEqual(out["route"], "simulated")

    def test_enhance_refuses_when_no_included_route(self):
        routes = providers.cached(self.store)
        for rid, r in list(routes.items()):
            r = dict(r)
            r["state"] = "READY_METERED_DISABLED"
            r["supported_modes"] = ["chat"]
            routes[rid] = r
        self.store.x(
            "INSERT INTO kv(k,v) VALUES('routes',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (json.dumps(routes),),
        )
        with self.assertRaises(ValueError) as ctx:
            prompt_generator.enhance(self.store, self.sup, self.svc, self.p["id"], "x" * 40)
        self.assertIn("metered", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
