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

    def test_preserves_internal_newlines_and_indentation(self):
        idea = (
            "Use this snippet in the prompt:\n"
            "```yaml\n"
            "services:\n"
            "  api:\n"
            "    image: app:latest\n"
            "```\n"
        )
        context = "\n  leading and trailing\n\tindented line\n"
        r = prompt_generator.generate(
            self.store, self.p["id"],
            idea=idea,
            mode="code",
            output_kind="ready",
            context=context,
        )
        self.assertIn("```yaml\nservices:\n  api:\n    image: app:latest\n```", r["prompt"])
        self.assertIn("leading and trailing\n\tindented line", r["prompt"])
        # enhance path uses the same cleaner
        cleaned = prompt_generator._clean("  a:\n    b: 1\n  ", 100)
        self.assertEqual(cleaned, "a:\n    b: 1")
        self.assertNotEqual(cleaned, "a: b: 1")

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

    def test_enhance_rejects_oversized_instead_of_truncating(self):
        too_big = "p" * (prompt_generator.MAX_PROMPT + 1)
        with self.assertRaises(ValueError) as ctx:
            prompt_generator.enhance(self.store, self.sup, self.svc, self.p["id"], too_big)
        self.assertIn("exceeds", str(ctx.exception).lower())
        # A full generate scaffold still fits the enhance limit.
        base = prompt_generator.generate(
            self.store, self.p["id"],
            idea="x" * prompt_generator.MAX_IDEA,
            mode="general",
            output_kind="ready",
            audience="a" * prompt_generator.MAX_FIELD,
            output_format="f" * prompt_generator.MAX_FIELD,
            constraints="c" * prompt_generator.MAX_FIELD,
            context="k" * prompt_generator.MAX_FIELD,
        )
        self.assertLessEqual(len(base["prompt"]), prompt_generator.MAX_PROMPT)
        out = prompt_generator.enhance(
            self.store, self.sup, self.svc, self.p["id"], base["prompt"], "simulated",
        )
        self.assertEqual(out["route"], "simulated")

    def test_enhance_falls_back_beyond_preferred_list(self):
        ok = {"state": "SIMULATED", "supported_modes": ["chat"]}
        bad = {"state": "READY_METERED_DISABLED", "supported_modes": ["chat"]}
        routes = {rid: dict(bad, id=rid) for rid in prompt_generator.ENHANCE_PREFERRED}
        routes["extra-local"] = dict(ok, id="extra-local")
        self.assertEqual(prompt_generator._pick_enhance_route(routes), "extra-local")
        self.assertEqual(
            prompt_generator._pick_enhance_route(routes, preferred="extra-local"),
            "extra-local",
        )
        routes["simulated"] = dict(ok, id="simulated")
        self.assertEqual(prompt_generator._pick_enhance_route(routes), "simulated")


if __name__ == "__main__":
    unittest.main()
