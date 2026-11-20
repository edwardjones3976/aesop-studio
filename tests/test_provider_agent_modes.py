"""Agent-mode argv regressions for remaining CLI lanes."""
import unittest
from unittest.mock import patch

from aesop_studio import providers


class ProviderAgentModes(unittest.TestCase):
    def test_claude_chat_cannot_write_but_agent_can(self):
        with patch.object(providers, "_claude_cmd", return_value=["claude"]):
            chat = providers.build_argv("claude", "chat", "C:/project", "out")
            agent = providers.build_argv("claude", "agent", "C:/project", "out")
            self.assertEqual(chat[chat.index("--tools") + 1], "")
            self.assertEqual(agent[agent.index("--permission-mode") + 1], "acceptEdits")
            self.assertTrue(any("Bash" in arg for arg in agent))

    def test_antigravity_prompt_limit_still_applies(self):
        with patch.object(providers, "_agy_cmd", return_value=["agy"]):
            with self.assertRaises(RuntimeError):
                providers.build_argv("antigravity", "chat", "C:/project", "out",
                                     prompt="x" * (providers.MAX_ARGV_PROMPT + 1))
