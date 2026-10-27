"""Provider registry: capability records verified by probing official, unmodified CLIs.

Routes never touch credential files; readiness comes from each CLI's own status command.
"""
from __future__ import annotations

import json
import re
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
               "CLAUDE_CODE_USE_VERTEX", "OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL", "AZURE_OPENAI_API_KEY",
               "PERPLEXITY_API_KEY"}


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


def _cursor_cmd() -> list[str] | None:
    """cursor-agent's own launcher is a .ps1; call its bundled node + index.js directly (no shell)."""
    import re
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "cursor-agent" / "versions"
    try:
        dirs = [d for d in base.iterdir() if d.is_dir() and re.match(r"^\d{4}\.\d{1,2}\.\d{1,2}(-\d{2}-\d{2}-\d{2})?-[a-f0-9]+$", d.name)]
    except OSError:
        return None
    if not dirs:
        return None
    key = lambda d: tuple(int(x) for x in d.name.split("-")[0].split("."))
    d = max(dirs, key=key)
    node, js = d / "node.exe", d / "index.js"
    return [str(node), str(js)] if node.is_file() and js.is_file() else None


def _agy_cmd() -> list[str] | None:
    exe = shutil.which("agy.exe") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe")
    return [exe] if exe and Path(exe).is_file() else None


def _copilot_cmd() -> list[str] | None:
    exe = shutil.which("copilot.exe")
    return [exe] if exe else None


def _grok_cmd() -> list[str] | None:
    exe = shutil.which("grok.exe") or str(Path.home() / ".grok" / "bin" / "grok.exe")
    return [exe] if exe and Path(exe).is_file() else None


# Routes whose CLI only accepts the prompt as an argument (never via a shell; Windows caps a command line at
# 32,767 characters, so longer prompts are refused rather than truncated).
ARGV_PROMPT_ROUTES = {"antigravity", "grok"}
MAX_ARGV_PROMPT = 24_000
# Live-verified CLI routes: an owner-triggered minimal call is the only proof of usable access + quota.
LIVE_VERIFY_ROUTES = {"cursor", "antigravity", "copilot", "grok", "zai"}
VERIFY_MAX_AGE_S = 7 * 24 * 3600


def _live_verification(store, rid: str) -> dict | None:
    if store is None:
        return None
    row = store.one("SELECT v FROM kv WHERE k=?", (f"verify:{rid}",))
    return json.loads(row["v"]) if row else None


VERIFY_TOKEN = "AESOP_VERIFY_OK"
# Paid-plan CLI lanes the owner uses day to day: keep their verification fresh in the background so they never drop
# out of the provider list after a quiet week, and re-check a failed verification instead of leaving it failed.
AUTO_REVERIFY_ROUTES = {"zai", "grok"}
REVERIFY_BEFORE_S = VERIFY_MAX_AGE_S - 24 * 3600
RECHECK_FAILED_S = 15 * 60


def due_reverify(store, now: float | None = None) -> list[str]:
    """Routes that were verified before and whose record is about to expire, or failed long enough ago to retry."""
    now = now or time.time()
    due = []
    for rid in sorted(AUTO_REVERIFY_ROUTES):
        ver = _live_verification(store, rid)
        if not ver:
            continue  # never verified: that first call stays an owner action
        age = now - ver.get("at", 0)
        if (ver.get("ok") and age > REVERIFY_BEFORE_S) or (not ver.get("ok") and age > RECHECK_FAILED_S):
            due.append(rid)
    return due




def verify_live(store, rid: str) -> dict:
    """Owner-triggered: one minimal read-only chat call proves sign-in + remaining quota for a CLI lane."""
    import tempfile
    from .security import redact
    if rid not in LIVE_VERIFY_ROUTES:
        raise ValueError(f"{rid} is not a live-verifiable CLI route")
    prompt = f"Reply with exactly: {VERIFY_TOKEN}"
    import shutil
    cwd = tempfile.mkdtemp(prefix="aesop-verify-")
    t0 = time.time()
    try:
        argv = build_argv(rid, "chat", cwd, str(Path(cwd) / "last.txt"), None, prompt=prompt)
        code, out = _contained(argv, 180, cwd=cwd, input_text=None if rid in ARGV_PROMPT_ROUTES else prompt)
        ok = VERIFY_TOKEN in out
        detail = "reply matched" if ok else redact(out.strip().splitlines()[-1] if out.strip() else f"exit {code}")
    except (OSError, RuntimeError) as e:
        ok, detail = False, f"{type(e).__name__}: {str(e)[:160]}"
    finally:
        shutil.rmtree(cwd, ignore_errors=True)
    rec = {"at": time.time(), "ok": ok, "detail": detail[:200], "latency_s": round(time.time() - t0, 1)}
    store.x("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (f"verify:{rid}", json.dumps(rec)))
    store.event("route_live_verification", None, route=rid, ok=ok, latency_s=rec["latency_s"])
    return rec


def _zai_cmd() -> list[str] | None:
    ps1 = Path.home() / ".claude" / "tools" / "zai" / "claude-zai.ps1"
    pwsh = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
    return [pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)] if ps1.is_file() and pwsh else None


def _sim_cmd() -> list[str]:
    return [sys.executable, "-I", str(Path(__file__).with_name("simulated_provider.py"))]


MAX_PROBE_OUTPUT = 64 * 1024


def _contained(argv: list[str], timeout: int, cwd: str | None = None, input_text: str | None = None) -> tuple[int, str]:
    """Run a short provider command inside a kill-on-close Job Object with a bounded timeout and bounded cleanup,
    so a hung CLI (or a descendant holding its pipes) can never hang or leak past the timeout."""
    from . import winjob
    env = {k: v for k, v in os.environ.items() if k.upper() not in BILLING_ENV}
    try:
        p = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    except OSError as e:
        return -1, str(e)
    job = winjob.contain(p.pid)
    try:
        try:
            out, _ = p.communicate(input_text.encode("utf-8") if input_text is not None else None, timeout=timeout)
        except subprocess.TimeoutExpired:
            if not winjob.terminate(job):
                p.kill()
            try:
                out, _ = p.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                for f in (p.stdout, p.stdin):
                    try:
                        f and f.close()
                    except OSError:
                        pass
                out = b""
            return -1, f"timed out after {timeout}s " + (out or b"")[:MAX_PROBE_OUTPUT].decode("utf-8", "replace")
        return p.returncode, (out or b"")[:MAX_PROBE_OUTPUT].decode("utf-8", "replace")
    finally:
        winjob.close(job)


def _run(argv: list[str], timeout: int = 30) -> tuple[int, str]:
    return _contained(argv, timeout)


def _base(provider, route_type, endpoint, modes, auth_method, billing_basis, limitations):
    return {"provider": provider, "route_type": route_type, "executable": endpoint, "version": None,
            "supported_modes": modes, "auth_method": auth_method, "auth_status": "UNVERIFIED",
            "billing_basis": billing_basis, "incremental_cost_status": "unknown",
            "permitted_data_classes": ["synthetic", "project_approved"],
            "filesystem_scope": ("working directory only, NOT an isolation boundary: the CLI runs as your Windows "
                                 "user and can read any file you can (chat: empty temp dir; agent: project root)"),
            "cancellation_behavior": "local process-tree termination; remote job stop not provable",
            "output_format": "text", "last_verified_at": None, "evidence": "", "limitations": limitations,
            "state": "UNVERIFIED"}


def probe(store=None) -> dict[str, dict]:
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

    from . import perplexity_api
    r = _base("perplexity", "api", "api.perplexity.ai /orchestrator/v1/chat/completions", ["chat"],
              "API key (PERPLEXITY_API_KEY)", "metered",
              "Text chat, streamed. Select a catalog model in Settings. Each call reserves its maximum cost; "
              "requires the mission permit or a monthly operating limit.")
    present = perplexity_api.key_present()
    r.update(state="READY_METERED_DISABLED" if present else "AUTH_REQUIRED",
             auth_status="api_key_present" if present else "missing", last_verified_at=now,
             evidence="PERPLEXITY_API_KEY present (value never shown)" if present else "Set PERPLEXITY_API_KEY",
             incremental_cost_status=f"metered; prices: {perplexity_api.PRICE_SOURCE}",
             filesystem_scope="none (only the previewed context is sent)",
             cancellation_behavior="local stream stopped; cancelled or cut-off requests retain exposure")
    routes["perplexity-orchestrator"] = r

    # ---- CLI lanes verified by an explicit owner-triggered live call (stored), plus local status where offered
    for rid, prov, cmdf, auth, billing_note in (
            ("cursor", "cursor", _cursor_cmd, "Cursor sign-in (cursor-agent login)",
             "Cursor plan usage; overage depends on account settings (not observable here)"),
            ("antigravity", "google", _agy_cmd, "Google sign-in (Antigravity)",
             "Antigravity/Gemini account quota; billing not observable here"),
            ("copilot", "github", _copilot_cmd, "GitHub sign-in (Copilot CLI)",
             "GitHub Copilot premium-request quota; paid overage only if enabled on the account"),
            ("grok", "xai", _grok_cmd, "xAI sign-in (SuperGrok, grok CLI)",
             "SuperGrok subscription quota (owner-confirmed paid plan)"),
            ("zai", "zai", _zai_cmd, "Z.ai GLM Coding Plan key (claude-zai launcher)",
             "Z.ai GLM Coding Plan credits (owner-confirmed paid plan); Claude Code client against Z.ai")):
        r = _base(prov, "official_cli", None, ["chat"], auth, "subscription_included", billing_note)
        r["filesystem_scope"] = ("chat only, read-only/ask/plan mode in an empty temp dir; not an isolation "
                                 "boundary — the CLI runs as your Windows user")
        cmd = cmdf()
        if not cmd:
            r.update(state="UNAVAILABLE", evidence=f"{rid} CLI not found on this PC", last_verified_at=now)
            routes[rid] = r
            continue
        if os.environ.get("AESOP_PROBE_OFFLINE") == "1":  # offline test runs never launch real CLIs
            r.update(state="UNVERIFIED", evidence="probe skipped (offline test mode)", last_verified_at=now)
            routes[rid] = r
            continue
        r["executable"] = Path(cmd[-1]).name if rid == "cursor" else Path(cmd[0]).name
        code, out = _run(cmd + ["--version"], timeout=30)
        lines = [l for l in out.strip().splitlines() if re.search(r"\d+\.\d+", l) and "WARNING" not in l]
        first = (lines or out.strip().splitlines() or [""])[0][:80]
        r["version"] = first if code == 0 and first else None
        signed_in = None
        if rid == "cursor":
            code, out = _run(cmd + ["status"], timeout=40)
            signed_in = code == 0 and "logged in" in out.lower()  # account identity is never stored
            r["auth_status"] = "signed_in" if signed_in else "not_signed_in"
        ver = _live_verification(store, rid)
        fresh = ver and now - ver.get("at", 0) < VERIFY_MAX_AGE_S
        if signed_in is False:
            r.update(state="AUTH_REQUIRED", evidence="cursor-agent status: not signed in; run `cursor-agent login`")
        elif fresh and ver.get("ok"):
            r.update(state="READY_INCLUDED", incremental_cost_status="plan quota (no $ visibility)",
                     evidence=f"live verification {time.strftime('%Y-%m-%d %H:%M', time.localtime(ver['at']))}: "
                              f"{ver.get('detail', 'ok')}")
        elif fresh:
            r.update(state="UNAVAILABLE", evidence=f"last live verification failed: {ver.get('detail', '')}"[:300])
        else:
            r.update(state="UNVERIFIED", evidence=("installed" + (" and signed in" if signed_in else "")
                                                   + "; run Verify (one minimal live call) to enable"))
        r["last_verified_at"] = (ver or {}).get("at") or now
        routes[rid] = r


    from . import research_routes
    have = research_routes.status() if os.environ.get("AESOP_PROBE_OFFLINE") != "1" else {"firecrawl": False,
                                                                                           "perplexity": False}
    r = _base("firecrawl", "research API", "api.firecrawl.dev", ["chat"], "api_key", "subscription_included",
              "Web search and page reading on the spot: ask a question for sourced results, or paste a URL to read "
              "the page. Uses Firecrawl plan credits (about 2 per search, 1 per page). No files or photos.")
    r.update(state="READY_INCLUDED" if have["firecrawl"] else "AUTH_REQUIRED", transport="research",
             auth_status="api_key" if have["firecrawl"] else "missing", last_verified_at=now,
             incremental_cost_status="Firecrawl plan credits (no $ per call)",
             evidence=("FIRECRAWL_API_KEY present (value never shown)" if have["firecrawl"]
                       else research_routes.key_problem("firecrawl") or "Set FIRECRAWL_API_KEY to enable"))
    routes["firecrawl"] = r
    r = _base("perplexity", "research API", "api.perplexity.ai", ["chat"], "api_key", "metered",
              "Answers with citations (Sonar), using the recent conversation. Metered per call: each call reserves "
              f"${research_routes.PPLX_RESERVE_USD:.2f} and settles from reported usage. No files or photos.")
    r.update(state="READY_METERED_DISABLED" if have["perplexity"] else "AUTH_REQUIRED", transport="research",
             auth_status="api_key" if have["perplexity"] else "missing", last_verified_at=now,
             incremental_cost_status=f"metered; {research_routes.PPLX_PRICE_NOTE}",
             evidence=("PERPLEXITY_API_KEY present (value never shown)" if have["perplexity"]
                       else research_routes.key_problem("perplexity") or "Set PERPLEXITY_API_KEY to enable"))
    routes["perplexity"] = r

    if os.environ.get("AESOP_SIMULATED_ROUTE") == "1":
        r = _base("simulated", "offline_simulation", "simulated_provider.py", ["chat", "agent"], "none",
                  "subscription_included", "Offline adapter simulation for tests. Never counted as a live provider.")
        r.update(state="SIMULATED", evidence="test-only", last_verified_at=now, incremental_cost_status="$0")
        routes["simulated"] = r
    return routes


def refresh(store: Store) -> dict[str, dict]:
    routes = _named(probe(store))
    store.x("INSERT INTO kv(k,v) VALUES('routes',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (json.dumps(routes),))
    store.event("routes_probed", None, states={k: v["state"] for k, v in routes.items()})
    return routes


# Owner naming rule (2026-10-23): each family is titled by its code-based product. OpenAI / ChatGPT / Codex all
# appear as "Codex"; route ids stay stable internally.
DISPLAY = {
    "codex": ("Codex", "Codex"), "openai-api": ("Codex API", "Codex"), "claude": ("Claude Code", "Claude Code"),
    "cursor": ("Cursor", "Cursor"), "antigravity": ("Antigravity", "Antigravity"),
    "copilot": ("Copilot CLI", "Copilot CLI"), "grok": ("Grok CLI", "Grok CLI"),
    "zai": ("Z.ai GLM", "Z.ai GLM"),
    "perplexity": ("Perplexity", "Perplexity"), "firecrawl": ("Firecrawl", "Firecrawl"),
    "perplexity-orchestrator": ("Perplexity Orchestrator", "Perplexity"),
    "simulated": ("Simulated (test only)", "Simulated"),
}


def display_name(route_id: str) -> str:
    return DISPLAY.get(route_id, (route_id, route_id))[0]


def _named(routes: dict) -> dict:
    for rid, r in routes.items():
        r["id"] = rid
        r["display_name"], r["family"] = DISPLAY.get(rid, (rid, rid))
        if rid in ("grok", "zai"):
            # Capabilities come from the installed adapter, including for cached verification records.
            r["supported_modes"] = ["chat", "agent"]
            r["filesystem_scope"] = ("chat: tools disabled in an empty temp dir; agent: file edits and shell "
                                     "commands in the project root; runs as your Windows user, not an isolation boundary")
    return routes


def cached(store: Store) -> dict[str, dict]:
    row = store.one("SELECT v FROM kv WHERE k='routes'")
    routes = _named(json.loads(row["v"]) if row else refresh(store))
    for rid in ("openai-api", "perplexity", "perplexity-orchestrator"):
        api = routes.get(rid)
        if api and api["state"] == "READY_METERED_DISABLED":
            from . import ledger
            purpose = ledger.active_purpose(store)
            if purpose:  # overlay live spend controls on the probed state
                routes[rid] = dict(api, state="READY_METERED", incremental_cost_status=f"metered; billing the "
                                   f"{purpose} envelope; {api['incremental_cost_status'].split('; ', 1)[-1]}")
    return routes


STUDY_ROUTES = ("claude", "codex", "simulated")   # CLIs that can load a per-run MCP server and a read-only sandbox


def usable(route: dict, mode: str) -> bool:
    if mode == "study":  # a reference study is a read-only agent run with the R.E.A. MCP server attached
        return route["state"] in ("READY_INCLUDED", "READY_METERED", "SIMULATED") and "agent" in route["supported_modes"] \
            and route.get("id") in STUDY_ROUTES
    return (route["state"] in ("READY_INCLUDED", "READY_METERED", "SIMULATED")
            and mode in route["supported_modes"])


def build_argv(route_id: str, mode: str, cwd: str, out_file: str, model: str | None = None,
               prompt: str | None = None, images: list[str] | None = None, study: dict | None = None) -> list[str]:
    """argv list (no shell). The prompt is always passed on stdin, never concatenated into a command.

    mode "study" (reference study): read-only sandbox, no shell/edit tools, and the R.E.A. MCP server attached from
    the explicit config in `study["mcp_config"]` so the run never depends on the owner's global registrations."""
    if mode == "study" and not (study and study.get("mcp_config") and study.get("ref_path")):
        raise RuntimeError("a study needs its MCP config and reference path")
    if route_id == "codex":
        cmd = _codex_cmd()
        if not cmd:
            raise RuntimeError("codex unavailable")
        sandbox = "read-only" if mode in ("chat", "study") else "workspace-write"
        argv = cmd + ["exec"]
        for img in images or []:  # each -i before the other flags, so the variadic option never eats them
            argv += ["-i", str(Path(cwd) / img)]
        argv += ["--skip-git-repo-check", "--color", "never", "-s", sandbox, "-C", cwd, "-o", out_file]
        if mode == "chat":
            argv.append("--ephemeral")
        if mode == "study":
            from .study import REA_ARGS, REA_COMMAND  # noqa: PLC0415
            args_toml = "[" + ", ".join(json.dumps(a) for a in REA_ARGS) + "]"
            argv += ["--ephemeral", "-c", f"mcp_servers.rea.command={json.dumps(REA_COMMAND)}",
                     "-c", f"mcp_servers.rea.args={args_toml}", "-c", "mcp_servers.rea.startup_timeout_sec=60",
                     "--add-dir", study["ref_path"]]
        if model:
            argv += ["-m", model]
        return argv + ["-"]
    if route_id == "claude":
        cmd = _claude_cmd()
        if not cmd:
            raise RuntimeError("claude unavailable")
        argv = cmd + ["-p", "--output-format", "text", "--no-session-persistence"]
        if mode == "chat":  # with photos, only Read (confined to this task's own folder) is enabled
            argv += ["--tools", "Read" if images else "", "--strict-mcp-config"]
        elif mode == "study":  # read-only inspection: file reads plus the rea MCP tools, nothing that writes or runs
            argv += ["--mcp-config", study["mcp_config"], "--strict-mcp-config", "--add-dir", study["ref_path"],
                     "--permission-mode", "default", "--allowedTools", "Read", "Glob", "Grep", "mcp__rea",
                     "--disallowedTools", "Bash", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "Task"]
        else:
            argv += ["--permission-mode", "acceptEdits",
                     "--disallowedTools", "Bash(rm:*)", "Bash(del:*)", "Bash(Remove-Item:*)", "WebFetch"]
        if model:
            argv += ["--model", model]
        return argv
    if route_id == "cursor" and mode == "chat":
        cmd = _cursor_cmd()
        if not cmd:
            raise RuntimeError("cursor-agent unavailable")
        argv = cmd + ["-p", "--output-format", "text", "--mode", "ask", "--trust", "--workspace", cwd]
        return argv + (["--model", model] if model else [])
    if route_id == "antigravity" and mode == "chat":
        cmd = _agy_cmd()
        if not cmd:
            raise RuntimeError("agy unavailable")
        if prompt is None or len(prompt) > MAX_ARGV_PROMPT:
            raise RuntimeError(f"Antigravity takes the prompt as an argument; context over {MAX_ARGV_PROMPT:,} "
                               "characters is refused")
        return cmd + ["--mode", "plan", "--print-timeout", "280s"] + (["--model", model] if model else []) + [
            "-p=" + prompt]
    if route_id == "copilot" and mode == "chat":
        cmd = _copilot_cmd()
        if not cmd:
            raise RuntimeError("copilot unavailable")
        return cmd + ["-s", "--no-color"] + (["--model", model] if model else [])  # prompt via stdin
    if route_id == "grok" and mode in ("chat", "agent"):
        cmd = _grok_cmd()
        if not cmd:
            raise RuntimeError("grok CLI unavailable")
        if prompt is None or len(prompt) > MAX_ARGV_PROMPT:
            raise RuntimeError(f"Grok takes the prompt as an argument; context over {MAX_ARGV_PROMPT:,} characters "
                               "is refused")
        permissions = (["--permission-mode", "default", "--tools", ""] if mode == "chat" else
                       ["--permission-mode", "acceptEdits", "--allow", "Bash"])
        return cmd + ["--cwd", cwd, "--no-plan"] + permissions + ["--output-format", "plain"] + (["-m", model] if model else []) + [
            "-p", prompt]
    if route_id == "zai" and mode in ("chat", "agent"):
        cmd = _zai_cmd()
        if not cmd:
            raise RuntimeError("claude-zai launcher unavailable")
        # Never pass an empty argument here: the launcher is a PowerShell script and Windows PowerShell drops empty
        # strings, so "--tools ''" arrived as a bare "--tools" and every Z.ai chat failed. Chat uses an explicit deny-list.
        permissions = (["--disallowedTools", "Bash,Edit,Write,WebFetch,WebSearch,NotebookEdit,Task"] if mode == "chat"
                       else ["--permission-mode", "acceptEdits", "--allowedTools", "Bash,Read,Edit,Write,Glob,Grep"])
        return cmd + (["-Model", model] if model else []) + [
            "-p", "--output-format", "text", "--no-session-persistence", "--strict-mcp-config"] + permissions
    if route_id == "simulated":
        return _sim_cmd() + [mode, out_file]
    raise RuntimeError(f"route {route_id} has no in-app execution path for {mode}")
