import tempfile
import unittest
from unittest.mock import patch

from aesop_studio import providers
from aesop_studio.store import Store


class ProviderAgentModes(unittest.TestCase):
    def test_agent_capability_preserves_auth_gate(self):
        for state, ready in (("READY_INCLUDED", True), ("UNVERIFIED", False)):
            for rid in ("grok", "zai"):
                routes = providers._named({rid: {"state": state, "supported_modes": ["chat"]}})
                self.assertEqual(providers.usable(routes[rid], "agent"), ready)
                self.assertEqual(routes[rid]["state"], state)

    def test_chat_cannot_write_but_agent_can(self):
        for rid in ("grok", "zai"):
            with self.subTest(provider=rid), patch.object(providers, f"_{rid}_cmd", return_value=[rid]):
                chat = providers.build_argv(rid, "chat", "C:/project", "out", prompt="test")
                agent = providers.build_argv(rid, "agent", "C:/project", "out", prompt="test")
                if rid == "grok":  # grok.exe is called directly, so an empty value survives
                    self.assertEqual(chat[chat.index("--tools") + 1], "")
                else:  # zai goes through PowerShell, which drops empty args: no empty argument allowed at all
                    self.assertNotIn("", chat)
                    self.assertIn("Bash", chat[chat.index("--disallowedTools") + 1])
                self.assertEqual(agent[agent.index("--permission-mode") + 1], "acceptEdits")
                self.assertNotIn("plan", agent)
                self.assertNotIn("--tools", agent)
                self.assertTrue(any("Bash" in arg for arg in agent))
                if rid == "grok":
                    self.assertEqual(agent[agent.index("--cwd") + 1], "C:/project")
                    self.assertIn("--no-plan", agent)
                else:
                    self.assertIn("--strict-mcp-config", agent)

    def test_balanced_pin_ignores_a_caller_model(self):
        cases = (
            ("codex", "chat", "_codex_cmd", ["codex"], None),
            ("claude", "agent", "_claude_cmd", ["claude"], None),
            ("cursor", "chat", "_cursor_cmd", ["cursor-agent"], None),
            ("antigravity", "chat", "_agy_cmd", ["agy"], "hi"),
            ("copilot", "chat", "_copilot_cmd", ["copilot"], None),
            ("grok", "agent", "_grok_cmd", ["grok"], "hi"),
            ("zai", "chat", "_zai_cmd", ["zai"], None),
        )
        for rid, mode, cmd, argv0, prompt in cases:
            with self.subTest(provider=rid), patch.object(providers, cmd, return_value=argv0):
                spec = providers.BALANCED[rid]
                argv = providers.build_argv(rid, mode, "C:/project", "out", model="not-the-pin", prompt=prompt)
                self.assertIn(spec["model"], argv)
                self.assertNotIn("not-the-pin", argv)
                if spec["reasoning"]:
                    self.assertIn(spec["reasoning"], " ".join(argv))

    def test_antigravity_quota_on_the_pin_uses_the_next_model(self):
        fault = ('AGY_ERROR: {"short_error":"RESOURCE_EXHAUSTED (code 429): Individual quota reached. '
                 'Resets in 77h5m2s.","status":"RESOURCE_EXHAUSTED"}')
        self.assertTrue(providers.model_quota_fault(fault))
        self.assertEqual(providers.quota_reset_seconds(fault), 77 * 3600 + 5 * 60 + 2)
        calls = []

        def contained(argv, timeout, cwd=None, input_text=None):
            calls.append(argv)
            model = argv[argv.index("--model") + 1]
            if model == "gemini-4-argon-medium":
                return 1, fault
            return 0, "AESOP_VERIFY_OK"

        store = Store(tempfile.mkdtemp(prefix="aesop-agy-"))
        try:
            with patch.object(providers, "_agy_cmd", return_value=["agy"]), patch.object(providers, "_contained", contained):
                rec = providers.verify_live(store, "antigravity")
            self.assertTrue(rec["ok"])
            self.assertEqual(rec["model"], "gemini-3.8-flash-medium")
            self.assertEqual(rec["exhausted_model"], "gemini-4-argon-medium")
            self.assertEqual([c[c.index("--model") + 1] for c in calls],
                             ["gemini-4-argon-medium", "gemini-3.8-flash-medium"])
            self.assertEqual(providers.active_model(store, "antigravity"), "gemini-3.8-flash-medium")
            with patch.object(providers, "_agy_cmd", return_value=["agy"]):
                argv = providers.build_argv("antigravity", "chat", "C:/project", "out",
                                            model="gemini-3.8-flash-medium", prompt="hi")
            self.assertIn("gemini-3.8-flash-medium", argv)
            self.assertNotIn("gemini-4-argon-medium", argv)
        finally:
            store.close()

    def test_grok_prompt_limit_still_applies_to_agent(self):
        with patch.object(providers, "_grok_cmd", return_value=["grok"]):
            with self.assertRaises(RuntimeError):
                providers.build_argv("grok", "agent", "C:/project", "out",
                                     prompt="x" * (providers.MAX_ARGV_PROMPT + 1))
