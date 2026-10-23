import unittest
from unittest.mock import patch

from aesop_studio import providers


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
                self.assertEqual(chat[chat.index("--tools") + 1], "")
                self.assertEqual(agent[agent.index("--permission-mode") + 1], "acceptEdits")
                self.assertNotIn("plan", agent)
                self.assertNotIn("--tools", agent)
                self.assertTrue(any("Bash" in arg for arg in agent))
                if rid == "grok":
                    self.assertEqual(agent[agent.index("--cwd") + 1], "C:/project")
                    self.assertIn("--no-plan", agent)
                else:
                    self.assertIn("--strict-mcp-config", agent)

    def test_grok_prompt_limit_still_applies_to_agent(self):
        with patch.object(providers, "_grok_cmd", return_value=["grok"]):
            with self.assertRaises(RuntimeError):
                providers.build_argv("grok", "agent", "C:/project", "out",
                                     prompt="x" * (providers.MAX_ARGV_PROMPT + 1))
