"""Provider lane discovery for Roundtables (presence and status only; never reads credentials).

Lanes are discovered live, not taken from a fixed list:
  1. every route in Studio's own capability registry (providers.cached),
  2. every documented lane whose official launcher is found on this machine (PATH or known install dirs),
  3. every provider credential registered in the owner's DPAPI provider store (file *names* only).
The nine documented lanes are a non-authoritative example: an undetected one is shown as NOT_DETECTED,
and anything discovered beyond them is listed too.
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from . import ledger, providers
from .store import Store

ADMINS = ("openai", "claude", "cursor")  # documented administrator identities (Codex, Claude Code, Cursor)
# Owner naming rule: each family is titled by its code-based product (OpenAI/ChatGPT/Codex -> "Codex").
DOCUMENTED_EXAMPLE = ["Codex", "Claude Code", "Cursor", "Director (local)", "Grok CLI", "Antigravity",
                      "Perplexity", "Firecrawl", "Copilot CLI", "Z.ai GLM Coding"]

_HOME = Path.home()
_LOCAL = Path(os.environ.get("LOCALAPPDATA", _HOME / "AppData" / "Local"))
CATALOG = [
    # id, name, lane_class, launcher names, extra known paths, studio route ids, billing note
    ("openai", "Codex", "admin", ["codex"], [], ["codex", "openai-api"],
     "codex: ChatGPT plan quota; openai-api: metered, mission/runtime envelopes"),
    ("claude", "Claude Code", "admin", ["claude"], [_HOME / ".local" / "bin" / "claude.exe"], ["claude"],
     "claude.ai plan quota"),
    ("cursor", "Cursor", "admin", ["cursor-agent"], [_LOCAL / "cursor-agent" / "cursor-agent.ps1"], ["cursor"],
     "Cursor plan; usage-based overage possible and not verifiable from here"),
    ("grok", "Grok CLI", "speaker", ["grok"], [_HOME / ".grok" / "bin" / "grok.exe"], ["grok"],
     "SuperGrok subscription quota (owner-confirmed paid plan)"),
    ("antigravity", "Antigravity", "speaker", ["agy", "antigravity"], [_LOCAL / "agy" / "bin" / "agy.exe"],
     ["antigravity"],
     "Google billing not verified as included"),
    ("perplexity", "Perplexity", "research", ["pplx"], [_HOME / ".local" / "bin" / "pplx.ps1"], ["perplexity"],
     "research tool; not a conversational speaker"),
    ("firecrawl", "Firecrawl", "research", ["firecrawl"], [], ["firecrawl"],
     "research tool (credit-based); not a conversational speaker"),
    ("copilot", "Copilot CLI", "speaker", ["copilot"], [], ["copilot"],
     "GitHub Copilot premium-request quota"),
    ("zai", "Z.ai GLM Coding", "speaker", ["claude-zai"], [_HOME / ".local" / "bin" / "claude-zai.cmd"], ["zai"],
     "Z.ai GLM Coding Plan credits (owner-confirmed paid plan)"),
    ("director-local", "Director (local)", "speaker", ["lms", "ollama"], [],
     ["director-lmstudio", "director-ollama"], "$0 provider spend; local CPU/GPU"),
]
_EXTS = ("", ".exe", ".cmd", ".bat", ".ps1")

# Live multi-provider sessions were approved by the owner (2026-10-23) but stay behind an explicit owner switch,
# off by default, changed only through the authenticated UI/API. The broker never changes it.
AUTH_KEY = "roundtable_live_authorized"
LIVE_GATE = {"code": "LIVE_ROUNDTABLES_OFF",
             "reason": "Live sessions are off. Use the Live switch at the top of this window (it turns on by itself "
                       "when you open Roundtable or War Room). Each session still needs roster consent, the sharing "
                       "acknowledgement and caps."}
MISSION_GATES = [LIVE_GATE]


def live_authorized(store: Store) -> bool:
    row = store.one("SELECT v FROM kv WHERE k=?", (AUTH_KEY,))
    return bool(row and row["v"] == "on")


def set_live_authorized(store: Store, on: bool) -> None:
    store.x("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (AUTH_KEY, "on" if on else "off"))
    store.event("roundtable_live_authorization", None, enabled=bool(on))


def _find(names: list[str], extra: list[Path]) -> str | None:
    for n in names:
        for ext in _EXTS:
            hit = shutil.which(n + ext)
            if hit:
                return hit
    for p in extra:
        if p.is_file():
            return str(p)
    return None


def _secret_store_names() -> list[str]:
    d = _HOME / ".codex" / "provider-mcp-secrets"
    try:
        return sorted(f.stem for f in d.glob("*.dpapi") if f.is_file())  # names only; never opened
    except OSError:
        return []


def discover(store: Store) -> dict:
    routes = providers.cached(store)
    funded = ledger.active_purpose(store)
    secrets = set(_secret_store_names())
    lanes, claimed_routes = [], set()
    for lid, name, cls, launchers, extra, route_ids, billing in CATALOG:
        path = _find(launchers, extra)
        own = [r for r in route_ids if r in routes]
        claimed_routes.update(own)
        verified = [r for r in own if routes[r]["state"] in providers.READY_STATES]
        status = [] if verified else [_route_status(r, routes[r]) for r in own]
        installed = bool(path or lid in secrets or any(st["installed"] for st in status))
        reasons, next_action = [], None
        if verified:
            readiness, conv = "VERIFIED_READY", "in_app_verified"
        elif installed:
            readiness = "INSTALLED_UNVERIFIED"
            chat = any(st["installed"] and "chat" in routes[st["route_id"]].get("supported_modes", []) for st in status)
            conv = "route_not_ready" if chat else "adapter_missing" if cls in ("admin", "speaker") else "none"
            next_action = _next_action(status)
            reasons += [_route_reason(st) for st in _ordered(status, next_action) if st["installed"]]
            if not status:
                reasons.append("Installed, but Studio has no in-app conversation adapter for this lane.")
        else:
            readiness, conv = "NOT_DETECTED", "none"
            reasons.append("No official launcher found on this PC.")
        if cls == "research":
            reasons.append("Research-only lane: may supply labelled source cards later; never counts as a speaker.")
        if cls == "review":
            reasons.append("Review-only lane: displayed but does not count as a conversational speaker.")
        metered_only = verified and all(routes[r]["billing_basis"] == "metered" for r in verified)
        if metered_only and not funded:
            reasons.append("Only a metered route is ready and no spend envelope is active.")
        cost = ("$0 provider spend; local CPU/GPU" if verified and all(routes[r]["billing_basis"] == "local"
                                                                       for r in verified)
                else "plan quota (no $ visibility)" if any(routes[r]["billing_basis"] == "subscription_included"
                                                      for r in verified)
                else "metered per token, tracked in the ledger" if verified else "unknown / not tracked")
        lanes.append({
            "id": lid, "name": name, "lane_class": cls, "detected": bool(path or own or lid in secrets),
            "detection": (f"launcher {Path(path).name}" if path else "Studio route registry" if own
                          else "credential registered in provider store" if lid in secrets else "not found"),
            "readiness": readiness, "route_type": _route_type(cls, verified, routes, _ordered(status, next_action)),
            "route_id": verified[0] if verified else None, "verified_routes": verified,
            "conversation_support": conv, "cost_visibility": cost, "billing_note": billing,
            "counts_as_speaker": cls in ("admin", "speaker") and conv == "in_app_verified"
                                 and not (metered_only and not funded),
            # route_status may carry raw CLI output (redacted); it is shown in the app, never exported
            "route_status": status, "next_action": next_action, "reasons": reasons})
    # anything registered in Studio or the secret store that the catalog doesn't know about
    known = {lid for lid, *_ in CATALOG}
    for rid, r in routes.items():
        if rid in claimed_routes:
            continue
        ready = r["state"] in providers.READY_STATES
        lanes.append({"id": f"route:{rid}", "name": r.get("display_name") or rid, "lane_class": "speaker",
                      "detected": True, "detection": "Studio route registry",
                      "readiness": "VERIFIED_READY" if ready else r["state"], "route_type": r["route_type"],
                      "route_id": rid if ready else None, "verified_routes": [rid] if ready else [],
                      "conversation_support": "in_app_verified" if ready and "chat" in r["supported_modes"] else "none",
                      "cost_visibility": r.get("incremental_cost_status", "unknown"), "billing_note": r["limitations"],
                      "counts_as_speaker": False,  # unknown/test lanes never inflate a roundtable count
                      "reasons": ["Discovered lane outside the documented roster; not counted as a speaker."]})
    for name in sorted(secrets - known - {"anthropic", "gemini", "xai"}):
        lanes.append({"id": f"secret:{name}", "name": name, "lane_class": "speaker", "detected": True,
                      "detection": "credential registered in provider store", "readiness": "INSTALLED_UNVERIFIED",
                      "route_type": "unknown", "route_id": None, "verified_routes": [],
                      "conversation_support": "adapter_missing", "cost_visibility": "unknown",
                      "billing_note": "", "counts_as_speaker": False,
                      "reasons": ["Registered credential only; no Studio adapter."]})
    return {"lanes": lanes, "documented_example": DOCUMENTED_EXAMPLE, "discovered_at": time.time(),
            "live_authorized": live_authorized(store),
            "mission_gates": [] if live_authorized(store) else [LIVE_GATE]}


def _day(ts) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts)) if ts else "an unknown date"


def _route_status(rid: str, r: dict) -> dict:
    """Why one of a lane's own routes is not ready, as plain fields (no credentials; evidence is redacted CLI text)."""
    state, evidence = r.get("state", "UNVERIFIED"), r.get("evidence") or ""
    installed = r.get("installed")
    if installed is None:  # routes without the field (codex, claude, APIs, local): infer from "not found" evidence
        installed = not (state == "UNAVAILABLE" and "not found" in evidence.lower())
    return {"route_id": rid, "name": r.get("display_name") or providers.display_name(rid), "state": state,
            "route_type": r.get("route_type", ""), "next_step": r.get("next_step"),
            "verifiable": bool(r.get("verifiable")), "installed": bool(installed),
            "verified_at": r.get("verified_at"), "verify_ok": r.get("verify_ok"),
            "expires_at": r.get("verify_expires_at"), "auth_method": r.get("auth_method", ""),
            "evidence": evidence[:300]}


def _next_action(status: list[dict]) -> dict | None:
    for st in status:
        if (st["verifiable"] and st["installed"] and st["state"] in ("UNVERIFIED", "UNAVAILABLE")
                and st["next_step"] == "verify"):
            return {"kind": "verify", "route_id": st["route_id"]}
    for st in status:
        if st["state"] == "AUTH_REQUIRED":
            return {"kind": "login", "route_id": st["route_id"]}
    for st in status:
        if st["next_step"] == "recheck":
            return {"kind": "recheck", "route_id": st["route_id"]}
    return None


def _ordered(status: list[dict], action: dict | None) -> list[dict]:
    """The route the next action is about comes first; the rest keep catalog order."""
    rid = action and action["route_id"]
    return sorted(status, key=lambda st: st["route_id"] != rid)


def _route_reason(st: dict) -> str:
    """Fixed, date-based sentence (no raw CLI output: reasons are copied into the shareable export packet)."""
    n, state, step = st["name"], st["state"], st["next_step"]
    if not st["installed"]:
        return f"{n}: CLI not found on this PC."
    if state == "AUTH_REQUIRED":
        how = st["auth_method"]
        return f"{n}: not signed in{f' ({how})' if how else ''}. Sign in, then Re-check."
    if step == "recheck":
        return f"{n}: the sign-in check timed out. Re-check (no model call)."
    if state == "UNAVAILABLE" and st["verify_ok"] is False:
        return (f"{n}: last verification failed on {_day(st['verified_at'])}. Verify again; the failure detail is "
                "shown with the route.")
    if state == "UNVERIFIED" and step == "verify" and st["verified_at"]:
        return (f"{n}: verification expired on {_day(st['expires_at'])} (last verified {_day(st['verified_at'])}). "
                "Verify with one test message to re-enable.")
    if state == "UNVERIFIED" and step == "verify":
        return f"{n}: installed but never verified in Studio. Verify with one test message to enable."
    if state == "READY_METERED_DISABLED":
        return f"{n}: metered route is off until you set a spend limit or turn on the mission permit."
    if state == "UNVERIFIED" and "offline test mode" in st["evidence"]:
        return f"{n}: not verified (probe skipped in offline test mode)."
    return f"{n}: route is {state}; see Providers for the evidence."


_NEEDS = {"verify": "verification needed", "login": "sign-in needed", "recheck": "sign-in check needed",
          "install": "not installed"}


def _route_type(cls, verified, routes, status=None) -> str:
    if not verified:
        if cls in ("admin", "speaker") and status:
            st = status[0]
            kind = {"official_cli": "official CLI", "local_model": "local model"}.get(
                st["route_type"], "API" if "api" in st["route_type"].lower() else "route")
            if not st["installed"]:
                need = "not installed"
            elif st["state"] == "AUTH_REQUIRED":
                need = "sign-in needed"
            elif st["state"] == "UNAVAILABLE" and st["verify_ok"] is False:
                need = "last verify failed"
            elif st["state"] == "READY_METERED_DISABLED":
                need = "metered, off"
            else:
                need = _NEEDS.get(st["next_step"], "not ready")
            return f"{kind} · {need}"
        return {"research": "research tool", "review": "review tool"}.get(cls, "official CLI (not integrated)")
    kinds = sorted({"local model" if routes[r]["billing_basis"] == "local"
                    else "separately billed API" if routes[r]["billing_basis"] == "metered"
                    else "official CLI · plan quota"
                    for r in verified})
    return " + ".join(kinds)
