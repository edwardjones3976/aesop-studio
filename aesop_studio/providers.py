"""Provider registry: capability records verified by probing official, unmodified CLIs.

Routes never touch credential files; readiness comes from each CLI's own status command.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .store import Store

STATES = ("UNVERIFIED", "AUTH_REQUIRED", "READY_INCLUDED", "READY_METERED", "READY_METERED_DISABLED",
          "HANDOFF_ONLY", "UNAVAILABLE", "BLOCKED_POLICY", "SIMULATED")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Variables that would redirect a CLI from subscription sign-in to a separately billed route.
BILLING_ENV = {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK",
               "CLAUDE_CODE_USE_VERTEX", "OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL", "AZURE_OPENAI_API_KEY"}


def _codex_cmd() -> list[str] | None:
    js = Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
    node = shutil.which("node")
    if js.is_file() and node:
        return [node, str(js)]  # avoid cmd.exe shim argument parsing
    exe = shutil.which("codex.exe")
    return [exe] if exe else None


def _claude_cmd() -> list[str] | None:
    exe = shutil.which("claude.exe") or shutil.which("claude")
    return [exe] if exe and exe.lower().endswith(".exe") else None


def _sim_cmd() -> list[str]:
    return [sys.executable, "-I", str(Path(__file__).with_name("simulated_provider.py"))]


def _run(argv: list[str], timeout: int = 30) -> tuple[int, str]:
    env = {k: v for k, v in os.environ.items() if k.upper() not in BILLING_ENV}
    try:
        p = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout, encoding="utf-8",
                           errors="replace", creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, str(e)


def _base(provider, route_type, endpoint, modes, auth_method, billing_basis, limitations):
    return {"provider": provider, "route_type": route_type, "executable": endpoint, "version": None,
            "supported_modes": modes, "auth_method": auth_method, "auth_status": "UNVERIFIED",
            "billing_basis": billing_basis, "incremental_cost_status": "unknown",
            "permitted_data_classes": ["synthetic", "project_approved"],
            "filesystem_scope": "chat: empty sandbox dir; agent: selected project root only",
            "cancellation_behavior": "local process-tree termination; remote job stop not provable",
            "output_format": "text", "last_verified_at": None, "evidence": "", "limitations": limitations,
            "state": "UNVERIFIED"}


def probe() -> dict[str, dict]:
    now = time.time()
    routes: dict[str, dict] = {}

    r = _base("openai", "official_cli", "codex exec", ["chat", "agent"], "ChatGPT sign-in (codex login)",
              "subscription_included", "Uses ChatGPT plan quota; generic chat runs as a read-only Codex exec.")
    cmd = _codex_cmd()
    if not cmd:
        r["state"] = "UNAVAILABLE"
        r["evidence"] = "codex CLI not found"
    else:
        r["executable"] = " ".join(Path(c).name for c in cmd)
        code, out = _run(cmd + ["--version"])
        r["version"] = out.strip().splitlines()[-1] if code == 0 and out.strip() else None
        code, out = _run(cmd + ["login", "status"])
        if code == 0 and "ChatGPT" in out:
            r.update(state="READY_INCLUDED", auth_status="signed_in_chatgpt", incremental_cost_status="$0 (plan quota)")
            r["evidence"] = "codex login status: Logged in using ChatGPT"
        elif code == 0 and "API key" in out:
            r.update(state="READY_METERED_DISABLED", auth_status="api_key",
                     incremental_cost_status="metered; disabled until owner sets operating limits")
            r["evidence"] = "codex login status reports API-key auth (metered)"
        else:
            r.update(state="AUTH_REQUIRED", auth_status="not_signed_in")
            r["evidence"] = "codex login status did not report a sign-in; run `codex login`"
    r["last_verified_at"] = now
    routes["codex"] = r

    r = _base("anthropic", "official_cli", "claude -p", ["chat", "agent"], "claude.ai sign-in",
              "subscription_included", "Uses Claude plan quota. Not an authorized biller: metered auth is blocked.")
    cmd = _claude_cmd()
    if not cmd:
        r["state"] = "UNAVAILABLE"
        r["evidence"] = "claude CLI not found"
    else:
        r["executable"] = "claude.exe"
        code, out = _run(cmd + ["--version"])
        r["version"] = out.strip().split()[0] if code == 0 and out.strip() else None
        code, out = _run(cmd + ["auth", "status"])
        try:
            st = json.loads(out[out.index("{"):out.rindex("}") + 1])
        except ValueError:
            st = {}
        if any(os.environ.get(k) for k in BILLING_ENV if k.startswith(("ANTHROPIC", "CLAUDE"))):
            r.update(state="BLOCKED_POLICY", auth_status="api_key_env_present",
                     incremental_cost_status="metered (non-OpenAI biller not authorized)")
            r["evidence"] = "Anthropic API/Bedrock/Vertex variable set; stripped from children but route held for owner review"
        elif st.get("loggedIn") and st.get("authMethod") == "claude.ai":
            r.update(state="READY_INCLUDED", auth_status="signed_in_claude_ai", incremental_cost_status="$0 (plan quota)")
            r["evidence"] = "claude auth status: loggedIn=true authMethod=claude.ai"
        elif st.get("loggedIn"):
            r.update(state="BLOCKED_POLICY", auth_status=str(st.get("authMethod")),
                     incremental_cost_status="non-subscription auth; not authorized")
            r["evidence"] = f"claude auth method {st.get('authMethod')} is not subscription-included"
        else:
            r.update(state="AUTH_REQUIRED", auth_status="not_signed_in")
            r["evidence"] = "claude auth status: not logged in; run `claude auth login`"
    r["last_verified_at"] = now
    routes["claude"] = r

    from . import openai_api
    r = _base("openai", "api", "api.openai.com /v1/responses (streaming)", ["chat"], "API key (OPENAI_API_KEY)",
              "metered", "Metered per token. Every call has a pre-reserved maximum cost; enabled only by the "
              "mission permit or an owner-set monthly operating limit.")
    r.update(state="READY_METERED_DISABLED" if openai_api.key_present() else "UNAVAILABLE",
             evidence=(f"Key source: {openai_api.key_source()} (presence only; value never shown)"
                       if openai_api.key_present() else "No OPENAI_API_KEY and no DPAPI provider secret found"),
             last_verified_at=now, version=f"models: {', '.join(openai_api.PRICES)}",
             incremental_cost_status=f"metered; prices: {openai_api.PRICE_SOURCE}",
             filesystem_scope="none (no file access; only the previewed context is sent)",
             cancellation_behavior="stream closed locally; tokens already generated may still bill (kept as exposure)")
    routes["openai-api"] = r

    for rid, prov, note in (("cursor", "cursor", "cursor-agent CLI not installed; open Cursor manually"),
                            ("perplexity", "perplexity", "Web app handoff; no verified no-charge API route"),
                            ("firecrawl", "firecrawl", "Handoff only inside Studio; built-in fetcher used instead")):
        r = _base(prov, "handoff", None, ["handoff"], "native app", "n/a", note)
        r.update(state="HANDOFF_ONLY", evidence=note, last_verified_at=now, incremental_cost_status="$0 (no call)")
        routes[rid] = r

    if os.environ.get("AESOP_SIMULATED_ROUTE") == "1":
        r = _base("simulated", "offline_simulation", "simulated_provider.py", ["chat", "agent"], "none",
                  "subscription_included", "Offline adapter simulation for tests. Never counted as a live provider.")
        r.update(state="SIMULATED", evidence="test-only", last_verified_at=now, incremental_cost_status="$0")
        routes["simulated"] = r
    return routes


def refresh(store: Store) -> dict[str, dict]:
    routes = probe()
    store.x("INSERT INTO kv(k,v) VALUES('routes',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (json.dumps(routes),))
    store.event("routes_probed", None, states={k: v["state"] for k, v in routes.items()})
    return routes


def cached(store: Store) -> dict[str, dict]:
    row = store.one("SELECT v FROM kv WHERE k='routes'")
    routes = json.loads(row["v"]) if row else refresh(store)
    api = routes.get("openai-api")
    if api and api["state"] == "READY_METERED_DISABLED":
        from . import ledger
        purpose = ledger.active_purpose(store)
        if purpose:  # overlay live spend controls on the probed state
            api = dict(api, state="READY_METERED", incremental_cost_status=f"metered; billing the {purpose} "
                       f"envelope; {api['incremental_cost_status'].split('; ', 1)[-1]}")
            routes["openai-api"] = api
    return routes


def usable(route: dict, mode: str) -> bool:
    return (route["state"] in ("READY_INCLUDED", "READY_METERED", "SIMULATED")
            and mode in route["supported_modes"])


def build_argv(route_id: str, mode: str, cwd: str, out_file: str, model: str | None = None) -> list[str]:
    """argv list (no shell). The prompt is always passed on stdin, never concatenated into a command."""
    if route_id == "codex":
        cmd = _codex_cmd()
        if not cmd:
            raise RuntimeError("codex unavailable")
        sandbox = "read-only" if mode == "chat" else "workspace-write"
        argv = cmd + ["exec", "--skip-git-repo-check", "--color", "never", "-s", sandbox, "-C", cwd,
                      "-o", out_file]
        if mode == "chat":
            argv.append("--ephemeral")
        if model:
            argv += ["-m", model]
        return argv + ["-"]
    if route_id == "claude":
        cmd = _claude_cmd()
        if not cmd:
            raise RuntimeError("claude unavailable")
        argv = cmd + ["-p", "--output-format", "text", "--no-session-persistence"]
        if mode == "chat":
            argv += ["--tools", "", "--strict-mcp-config"]
        else:
            argv += ["--permission-mode", "acceptEdits",
                     "--disallowedTools", "Bash(rm:*)", "Bash(del:*)", "Bash(Remove-Item:*)", "WebFetch"]
        if model:
            argv += ["--model", model]
        return argv
    if route_id == "simulated":
        return _sim_cmd() + [mode, out_file]
    raise RuntimeError(f"route {route_id} has no in-app execution path")
