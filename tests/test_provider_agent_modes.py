import json
import tempfile
import unittest
from unittest.mock import patch

from aesop_studio import providers
from aesop_studio.store import Store


class ProviderAgentModes(unittest.TestCase):
    def test_agent_capability_preserves_auth_gate(self):
        for state, ready in (("READY_INCLUDED", True), ("UNVERIFIED", False)):
            for rid in ("grok", "zai"):
                routes = providers._named(
                    {rid: {"state": state, "supported_modes": ["chat"]}}
                )
                self.assertEqual(providers.usable(routes[rid], "agent"), ready)
                self.assertEqual(routes[rid]["state"], state)

    def test_administrator_agent_argv(self):
        with patch.object(providers, "_claude_cmd", return_value=["claude"]):
            agent = providers.build_argv("claude", "agent", "C:/project", "out")
            self.assertEqual(
                agent[agent.index("--permission-mode") + 1], "bypassPermissions"
            )
            self.assertNotIn("--disallowedTools", agent)
        with patch.object(providers, "_codex_cmd", return_value=["codex"]):
            chat = providers.build_argv("codex", "chat", "C:/project", "out")
            agent = providers.build_argv("codex", "agent", "C:/project", "out")
            self.assertEqual(chat[chat.index("-s") + 1], "read-only")
            self.assertEqual(agent[agent.index("-s") + 1], "danger-full-access")

    def test_chat_cannot_write_but_agent_can(self):
        for rid in ("grok", "zai"):
            with (
                self.subTest(provider=rid),
                patch.object(providers, f"_{rid}_cmd", return_value=[rid]),
            ):
                chat = providers.build_argv(
                    rid, "chat", "C:/project", "out", prompt="test"
                )
                agent = providers.build_argv(
                    rid, "agent", "C:/project", "out", prompt="test"
                )
                if (
                    rid == "grok"
                ):  # grok.exe is called directly, so an empty value survives
                    self.assertEqual(chat[chat.index("--tools") + 1], "")
                else:  # zai goes through PowerShell, which drops empty args: no empty argument allowed at all
                    self.assertNotIn("", chat)
                    self.assertIn("Bash", chat[chat.index("--disallowedTools") + 1])
                self.assertEqual(
                    agent[agent.index("--permission-mode") + 1], "acceptEdits"
                )
                self.assertNotIn("plan", agent)
                self.assertNotIn("--tools", agent)
                self.assertTrue(any("Bash" in arg for arg in agent))
                if rid == "grok":
                    self.assertEqual(agent[agent.index("--cwd") + 1], "C:/project")
                    self.assertIn("--no-plan", agent)
                else:
                    self.assertIn("--strict-mcp-config", agent)

    def test_cursor_chat_is_ask_and_agent_is_forced_edit_mode(self):
        with patch.object(providers, "_cursor_cmd", return_value=["node", "index.js"]):
            chat = providers.build_argv("cursor", "chat", "C:/project", "out")
            agent = providers.build_argv("cursor", "agent", "C:/project", "out")
        self.assertEqual(chat[chat.index("--mode") + 1], "ask")
        self.assertNotIn("--force", chat)
        self.assertNotIn(
            "--mode", agent
        )  # cursor-agent's default mode is the one that edits
        self.assertIn("--force", agent)
        for a in (chat, agent):
            self.assertEqual(a[a.index("--workspace") + 1], "C:/project")
            self.assertIn("--trust", a)
            self.assertEqual(
                a[a.index("--model") + 1], providers.BALANCED["cursor"]["model"]
            )
        routes = providers._named(
            {"cursor": {"state": "READY_INCLUDED", "supported_modes": ["chat"]}}
        )
        self.assertTrue(providers.usable(routes["cursor"], "agent"))

    def test_gemini_and_zcode_argv(self):
        with patch.object(providers, "_gemini_cmd", return_value=["node", "gemini.js"]):
            chat = providers.build_argv(
                "gemini", "chat", "C:/project", "out", extra_dirs=["C:/ref"]
            )
            agent = providers.build_argv("gemini", "agent", "C:/project", "out")
        self.assertEqual(chat[chat.index("--approval-mode") + 1], "plan")
        self.assertEqual(agent[agent.index("--approval-mode") + 1], "auto_edit")
        self.assertEqual(chat[chat.index("--include-directories") + 1], "C:/ref")
        self.assertIn("--skip-trust", chat)
        self.assertNotIn("-m", chat)  # no Studio pin: the CLI default model
        with patch.object(providers, "_zcode_cmd", return_value=["node", "zcode.cjs"]):
            z = providers.build_argv(
                "zcode", "chat", "C:/project", "out", prompt="hello"
            )
            self.assertEqual(z[-2:], ["-p", "hello"])
            with self.assertRaises(RuntimeError):
                providers.build_argv(
                    "zcode", "agent", "C:/project", "out", prompt="hello"
                )
        self.assertIn("zcode", providers.ARGV_PROMPT_ROUTES)
        self.assertNotIn(
            "gemini", providers.ARGV_PROMPT_ROUTES
        )  # context travels on stdin

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
            with (
                self.subTest(provider=rid),
                patch.object(providers, cmd, return_value=argv0),
            ):
                spec = providers.BALANCED[rid]
                argv = providers.build_argv(
                    rid, mode, "C:/project", "out", model="not-the-pin", prompt=prompt
                )
                self.assertIn(spec["model"], argv)
                self.assertNotIn("not-the-pin", argv)
                if spec["reasoning"]:
                    self.assertIn(spec["reasoning"], " ".join(argv))

    def test_gemini_api_key_blocks_subscription_route(self):
        store = Store(tempfile.mkdtemp(prefix="aesop-gem-"))
        try:
            with (
                patch.object(
                    providers, "_gemini_cmd", return_value=["node", "gemini.js"]
                ),
                patch.object(providers, "gemini_api_key_configured", return_value=True),
                patch.object(providers, "gemini_oauth_included", return_value=False),
            ):
                routes = providers.probe(store)
            self.assertEqual(routes["gemini"]["state"], "BLOCKED_POLICY")
            self.assertEqual(routes["gemini"]["auth_status"], "api_key_present")
        finally:
            store.close()

    def test_gemini_api_key_with_oauth_not_policy_blocked(self):
        store = Store(tempfile.mkdtemp(prefix="aesop-gem-"))
        try:
            import os
            import time as _time

            store.x(
                "INSERT INTO kv(k,v) VALUES(?,?)",
                (
                    "verify:gemini",
                    json.dumps({"at": _time.time(), "ok": True, "detail": "ok"}),
                ),
            )

            def fake_run(argv, timeout=30):
                return 0, "gemini 1.0.0"

            with (
                patch.dict(os.environ, {"AESOP_PROBE_OFFLINE": ""}, clear=False),
                patch.object(providers, "_run", fake_run),
                patch.object(
                    providers, "_gemini_cmd", return_value=["node", "gemini.js"]
                ),
                patch.object(providers, "gemini_api_key_configured", return_value=True),
                patch.object(providers, "gemini_oauth_included", return_value=True),
            ):
                os.environ.pop("AESOP_PROBE_OFFLINE", None)
                routes = providers.probe(store)
                self.assertEqual(routes["gemini"]["state"], "READY_INCLUDED")
                self.assertFalse(providers.gemini_policy_blocked())
        finally:
            store.close()

    def test_gemini_policy_blocked_matches_probe_and_verify_live(self):
        store = Store(tempfile.mkdtemp(prefix="aesop-gem-vfy-"))
        try:
            import os
            import time as _time

            store.x(
                "INSERT INTO kv(k,v) VALUES(?,?)",
                (
                    "verify:gemini",
                    json.dumps({"at": _time.time(), "ok": True, "detail": "ok"}),
                ),
            )

            def fake_run(argv, timeout=30):
                return 0, "gemini 1.0.0"

            cases = (
                (True, False, True, "BLOCKED_POLICY"),
                (True, True, False, "READY_INCLUDED"),
            )
            for key, oauth, blocked, expect_state in cases:
                with self.subTest(key=key, oauth=oauth):
                    with (
                        patch.dict(
                            os.environ, {"AESOP_PROBE_OFFLINE": ""}, clear=False
                        ),
                        patch.object(providers, "_run", fake_run),
                        patch.object(
                            providers, "gemini_api_key_configured", return_value=key
                        ),
                        patch.object(
                            providers, "gemini_oauth_included", return_value=oauth
                        ),
                        patch.object(
                            providers, "_gemini_cmd", return_value=["node", "gemini.js"]
                        ),
                        patch.object(
                            providers,
                            "_contained",
                            return_value=(0, providers.VERIFY_TOKEN),
                        ),
                        patch.object(
                            providers, "build_argv", return_value=["node", "gemini.js"]
                        ),
                    ):
                        os.environ.pop("AESOP_PROBE_OFFLINE", None)
                        self.assertEqual(providers.gemini_policy_blocked(), blocked)
                        rec = providers.verify_live(store, "gemini")
                        self.assertEqual(rec["ok"], not blocked)
                        routes = providers.probe(store)
                        self.assertEqual(routes["gemini"]["state"], expect_state)
        finally:
            store.close()

    def test_gemini_oauth_allows_included_when_verified(self):
        store = Store(tempfile.mkdtemp(prefix="aesop-gem-"))
        try:
            import os
            import time as _time

            store.x(
                "INSERT INTO kv(k,v) VALUES(?,?)",
                (
                    "verify:gemini",
                    json.dumps({"at": _time.time(), "ok": True, "detail": "ok"}),
                ),
            )

            def fake_run(argv, timeout=30):
                return 0, "gemini 1.0.0"

            with (
                patch.dict(os.environ, {"AESOP_PROBE_OFFLINE": ""}, clear=False),
                patch.object(providers, "_run", fake_run),
                patch.object(
                    providers, "_gemini_cmd", return_value=["node", "gemini.js"]
                ),
                patch.object(
                    providers, "gemini_api_key_configured", return_value=False
                ),
                patch.object(providers, "gemini_oauth_included", return_value=True),
            ):
                os.environ.pop("AESOP_PROBE_OFFLINE", None)
                routes = providers.probe(store)
            self.assertEqual(routes["gemini"]["state"], "READY_INCLUDED")
        finally:
            store.close()

    def test_grok_prompt_limit_still_applies_to_agent(self):
        with patch.object(providers, "_grok_cmd", return_value=["grok"]):
            with self.assertRaises(RuntimeError):
                providers.build_argv(
                    "grok",
                    "agent",
                    "C:/project",
                    "out",
                    prompt="x" * (providers.MAX_ARGV_PROMPT + 1),
                )

    def test_verify_live_blocks_gemini_api_key_without_cli(self):
        store = Store(tempfile.mkdtemp(prefix="aesop-gem-vfy-"))
        try:
            with (
                patch.object(providers, "gemini_api_key_configured", return_value=True),
                patch.object(providers, "gemini_oauth_included", return_value=False),
                patch.object(providers, "_contained") as contained,
            ):
                self.assertTrue(providers.gemini_policy_blocked())
                rec = providers.verify_live(store, "gemini")
            self.assertFalse(rec["ok"])
            self.assertIn("blocked by policy", rec["detail"])
            self.assertEqual(rec["latency_s"], 0.0)
            contained.assert_not_called()
            row = store.one("SELECT v FROM kv WHERE k=?", ("verify:gemini",))
            self.assertFalse(json.loads(row["v"])["ok"])
        finally:
            store.close()

    def test_verify_live_gemini_oauth_runs_normal_path(self):
        store = Store(tempfile.mkdtemp(prefix="aesop-gem-vfy-"))
        try:
            with (
                patch.object(
                    providers, "gemini_api_key_configured", return_value=False
                ),
                patch.object(providers, "gemini_oauth_included", return_value=True),
                patch.object(
                    providers, "_contained", return_value=(0, providers.VERIFY_TOKEN)
                ),
                patch.object(
                    providers, "build_argv", return_value=["node", "gemini.js"]
                ),
            ):
                rec = providers.verify_live(store, "gemini")
            self.assertTrue(rec["ok"])
        finally:
            store.close()

    def test_billing_env_includes_gemini_key_names(self):
        for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
            self.assertIn(name, providers.BILLING_ENV)


if __name__ == "__main__":
    unittest.main()
