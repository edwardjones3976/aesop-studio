"""Reference studies (R.E.A.): registry safety, study-mode argv, result intake into notebook + plan, room hook."""
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["AESOP_SIMULATED_ROUTE"] = "1"
os.environ["AESOP_PROBE_OFFLINE"] = "1"

from aesop_studio import plan, providers, researcher, study  # noqa: E402
from aesop_studio.services import Services  # noqa: E402
from aesop_studio.store import Store  # noqa: E402
from aesop_studio.tasks import Supervisor  # noqa: E402


class StudyBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-study-"))
        (self.tmp / "p").mkdir()
        app = self.tmp / "apps" / "RefApp" / "resources" / "app"
        app.mkdir(parents=True)
        (app / "main.js").write_text("// ref", encoding="utf-8")
        self.app_root = self.tmp / "apps" / "RefApp"
        self.store = Store(self.tmp / "d")
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        providers.refresh(self.store)
        self.p = self.svc.create_project("P", str(self.tmp / "p"), "simulated")

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestRegistry(StudyBase):
    def test_add_detects_electron_layout_and_refuses_bad_folders(self):
        r = study.add_ref(self.store, str(self.app_root), "Ref App")
        self.assertEqual((r["kind"], Path(r["target"]).name, r["name"]), ("electron", "app", "Ref App"))
        with self.assertRaises(ValueError):
            study.add_ref(self.store, str(self.app_root))  # duplicate
        for bad in (str(Path.home() / ".ssh"), str(Path.home()), "C:\\", "relative\\path", str(self.tmp / "missing")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                study.add_ref(self.store, bad)
        self.assertEqual([x["name"] for x in study.refs(self.store)], ["Ref App"])
        study.remove_ref(self.store, r["id"])
        self.assertEqual(study.refs(self.store), [])
        with self.assertRaises(KeyError):
            study.remove_ref(self.store, r["id"])

    def test_status_and_ack(self):
        st = study.status(self.store)
        self.assertFalse(st["ack"])
        self.assertIn("simulated", st["providers"])
        self.assertTrue(all(Path(c["path"]).is_dir() for c in st["candidates"]))
        study.set_ack(self.store, True)
        self.assertTrue(study.ack(self.store))


class TestArgv(unittest.TestCase):
    def test_study_mode_is_read_only_with_rea_attached(self):
        st = {"mcp_config": "C:/d/studies/s1/mcp.json", "ref_path": "C:/apps/Ref/resources/app"}
        with patch.object(providers, "_claude_cmd", return_value=["claude"]):
            a = providers.build_argv("claude", "study", "C:/d/studies/s1", "out", study=st)
            self.assertEqual(a[a.index("--mcp-config") + 1], st["mcp_config"])
            self.assertIn("--strict-mcp-config", a)
            self.assertEqual(a[a.index("--add-dir") + 1], st["ref_path"])
            allowed = a[a.index("--allowedTools") + 1: a.index("--disallowedTools")]
            self.assertEqual(allowed, ["Read", "Glob", "Grep", "mcp__rea"])
            self.assertIn("Bash", a[a.index("--disallowedTools") + 1:])
            self.assertNotIn("acceptEdits", a)
            with self.assertRaises(RuntimeError):
                providers.build_argv("claude", "study", "C:/d", "out")  # no study record: refused
        with patch.object(providers, "_codex_cmd", return_value=["codex"]):
            a = providers.build_argv("codex", "study", "C:/d/studies/s1", "out", study=st)
            self.assertEqual(a[a.index("-s") + 1], "read-only")
            joined = " ".join(a)
            self.assertIn("mcp_servers.rea.command=", joined)
            self.assertIn("rea-agents@" + study.REA_VERSION, joined)
            self.assertEqual(a[a.index("--add-dir") + 1], st["ref_path"])

    def test_usable_for_study(self):
        routes = providers._named({"claude": {"state": "READY_INCLUDED", "supported_modes": ["chat", "agent"]},
                                   "grok": {"state": "READY_INCLUDED", "supported_modes": ["chat"]},
                                   "zai": {"state": "READY_INCLUDED", "supported_modes": ["chat", "agent"]}})
        self.assertTrue(providers.usable(routes["claude"], "study"))
        self.assertFalse(providers.usable(routes["grok"], "study"))
        self.assertFalse(providers.usable(routes["zai"], "study"))  # agent-capable but cannot load a per-run MCP server


class TestParse(unittest.TestCase):
    def test_parse_takes_the_last_fenced_block_and_bounds_it(self):
        text = ("## Report\nstuff ```json {\"findings\": []} ``` not the last one\n\n```json\n"
                + json.dumps({"findings": [{"claim": "A", "evidence": "x.js", "limitation": ""}] * 20,
                              "steps": [{"step": "Do one"}, "Do two", "x"]}) + "\n```")
        d = study.parse(text)
        self.assertEqual(len(d["findings"]), study.MAX_FINDINGS)
        self.assertEqual(d["steps"], ["Do one", "Do two"])
        self.assertTrue(d["report"].startswith("## Report"))
        self.assertEqual(study.parse("no json here"), {"findings": [], "steps": [], "report": "no json here"})


class TestRunThrough(StudyBase):
    def _run(self, topic="chat composer"):
        ref = study.add_ref(self.store, str(self.app_root), "Ref App")
        study.set_ack(self.store, True)
        st = study.start(self.store, self.sup, self.svc, self.p["id"], ref["id"], topic)
        end = time.time() + 30
        while time.time() < end and st["state"] == "RUNNING":
            time.sleep(0.2)
            st = study.get(self.store, st["id"])
        return ref, st

    def test_study_needs_ack_and_a_registered_ref(self):
        ref = study.add_ref(self.store, str(self.app_root), "Ref App")
        with self.assertRaises(ValueError):
            study.start(self.store, self.sup, self.svc, self.p["id"], ref["id"], "composer")
        study.set_ack(self.store, True)
        with self.assertRaises(KeyError):
            study.start(self.store, self.sup, self.svc, self.p["id"], "ref_nope", "composer")
        with self.assertRaises(ValueError):
            study.start(self.store, self.sup, self.svc, self.p["id"], ref["id"], "x")

    def test_findings_reach_notebook_and_plan(self):
        ref, st = self._run()
        self.assertEqual(st["state"], "DONE", st.get("error"))
        self.assertEqual([f["claim"] for f in st["findings"]][:1], ["Drafts are saved per conversation on every keystroke"])
        self.assertIn("Observed behavior", st["report"])
        nb = self.svc.notebook(self.p["id"])
        self.assertEqual([s["kind"] for s in nb["sources"]], ["study"])
        self.assertEqual(nb["sources"][0]["private"], 1)
        self.assertEqual(len(nb["findings"]), 2)
        self.assertEqual(nb["findings"][0]["status"], "cited")
        items = plan.list_items(self.store, self.sup, self.p["id"])
        self.assertEqual([i["source"] for i in items], ["Study: Ref App"] * 2)
        self.assertEqual(items[0]["content"], "Keep an unsent draft per conversation in localStorage")
        # the study's own folder holds the MCP config and the task never touched the project
        t = self.sup.get(st["task_id"])
        cp = json.loads(t["checkpoint"])
        self.assertEqual(cp["mode"], "study")
        self.assertTrue(Path(cp["study"]["mcp_config"]).is_file())
        self.assertEqual(json.loads(Path(cp["study"]["mcp_config"]).read_text())["mcpServers"]["rea"]["args"][-1], "mcp")
        self.assertFalse(t["cwd"].startswith(self.p["root"]))
        self.assertEqual(sorted(os.listdir(self.p["root"])), [])
        texts = [a["text"] for a in plan.activity(self.store, self.p["id"])]
        self.assertTrue(any(t.startswith("Studied Ref App for chat composer: 2 finding(s), 2 step(s)") for t in texts))
        # a second study with the same steps does not duplicate plan items
        _, st2 = self._run_again(ref)
        self.assertEqual(len(plan.list_items(self.store, self.sup, self.p["id"])), 2)
        self.assertEqual(len(study.list_studies(self.store, self.p["id"])), 2)

    def _run_again(self, ref):
        st = study.start(self.store, self.sup, self.svc, self.p["id"], ref["id"], "chat composer again")
        end = time.time() + 30
        while time.time() < end and st["state"] == "RUNNING":
            time.sleep(0.2)
            st = study.get(self.store, st["id"])
        return ref, st

    def test_study_does_not_count_as_the_project_writer(self):
        ref = study.add_ref(self.store, str(self.app_root), "Ref App")
        study.set_ack(self.store, True)
        self.store.x("INSERT INTO kv(k,v) VALUES(?, 'on')", (f"agent_ack:{self.p['id']}",))
        st = study.start(self.store, self.sup, self.svc, self.p["id"], ref["id"], "composer")
        tid = self.sup.create(self.p, "simulated", "WRITE a helper", mode="agent", timeout=30)
        self.assertNotEqual(self.sup.get(tid)["state"], "BLOCKED_OWNER")
        end = time.time() + 30
        while time.time() < end and study.get(self.store, st["id"])["state"] == "RUNNING":
            time.sleep(0.2)


class TestIntake(StudyBase):
    def test_finish_reads_printed_output_when_result_file_is_empty(self):
        """Claude Code prints its answer (task log); only Codex writes the result file."""
        ref = study.add_ref(self.store, str(self.app_root), "Ref App")
        study.set_ack(self.store, True)
        st = study.start(self.store, self.sup, self.svc, self.p["id"], ref["id"], "composer")
        end = time.time() + 30
        while time.time() < end and study.get(self.store, st["id"])["state"] == "RUNNING":
            time.sleep(0.2)
        t = dict(self.sup.get(st["task_id"]))
        t["checkpoint"] = json.dumps({**json.loads(t["checkpoint"]), "result": ""})
        self.store.x("UPDATE studies SET state='RUNNING', findings='[]', steps='[]' WHERE id=?", (st["id"],))
        out = study.finish(self.store, self.sup, self.svc, self.p["id"], st["id"], t, ref, "composer", "simulated")
        self.assertEqual(out["state"], "DONE")
        self.assertEqual(len(out["findings"]), 2)


class TestRoomHook(unittest.TestCase):
    def test_study_request_grammar(self):
        self.assertEqual(researcher.study_request("study Cursor chat composer drafts"), ("Cursor", "chat composer drafts"))
        self.assertEqual(researcher.study_request('study "VS Code" command palette'), ("VS Code", "command palette"))
        self.assertEqual(researcher.study_request("study of Perplexity: citations UI"), ("Perplexity", "citations UI"))
        self.assertIsNone(researcher.study_request("sqlite vs lmdb durability"))
        self.assertIsNone(researcher.study_request("study X"))
        self.assertEqual(researcher.requests_in("RESEARCH: study Cursor composer"), ["study Cursor composer"])


if __name__ == "__main__":
    unittest.main()
