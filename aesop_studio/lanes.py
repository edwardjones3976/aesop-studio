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
DOCUMENTED_EXAMPLE = ["Codex", "Claude Code", "Cursor", "Grok CLI", "Antigravity", "Perplexity", "Firecrawl",
                      "Copilot CLI", "Z.ai GLM Coding"]

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
     "xAI billing not verified as included"),
    ("antigravity", "Antigravity", "speaker", ["agy", "antigravity"], [_LOCAL / "agy" / "bin" / "agy.exe"],
     ["antigravity"],
     "Google billing not verified as included"),
    ("perplexity", "Perplexity", "research", ["pplx"], [_HOME / ".local" / "bin" / "pplx.ps1"], ["perplexity"],
     "research tool; not a conversational speaker"),
    ("firecrawl", "Firecrawl", "research", ["firecrawl"], [], ["firecrawl"],
     "research tool (credit-based); not a conversational speaker"),
    ("copilot", "Copilot CLI", "speaker", ["copilot"], [], ["copilot"],
     "GitHub Copilot premium-request quota"),
    ("zai", "Z.ai GLM Coding", "speaker", ["claude-zai"], [_HOME / ".local" / "bin" / "claude-zai.cmd"], [],
     "paid non-OpenAI biller: blocked by the $165 mission's OpenAI-only rule"),
]
_EXTS = ("", ".exe", ".cmd", ".bat", ".ps1")

# Live multi-provider sessions were approved by the owner (2026-10-23) but stay behind an explicit owner switch,
# off by default, changed only through the authenticated UI/API. The broker never changes it.
AUTH_KEY = "roundtable_live_authorized"
LIVE_GATE = {"code": "LIVE_ROUNDTABLES_OFF",
             "reason": "Live roundtables are switched off. Turn them on under Evidence → Spend controls → Live "
                       "roundtables. Each session still needs roster consent, the sharing acknowledgement and caps."}
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
        verified = [r for r in own if routes[r]["state"] in ("READY_INCLUDED", "READY_METERED")]
        reasons = []
        if verified:
            readiness, conv = "VERIFIED_READY", "in_app_verified"
        elif lid == "zai" and path:
            readiness, conv = "BLOCKED_POLICY", "adapter_missing"
            reasons.append("Z.ai is a paid non-OpenAI biller; this mission allows $0 non-OpenAI spend.")
        elif path or own or lid in secrets:
            readiness, conv = "INSTALLED_UNVERIFIED", "adapter_missing" if cls in ("admin", "speaker") else "none"
            reasons.append("Installed, but Studio has no verified in-app conversation adapter for this lane.")
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
        cost = ("plan quota (no $ visibility)" if any(routes[r]["billing_basis"] == "subscription_included"
                                                      for r in verified)
                else "metered per token, tracked in the ledger" if verified else "unknown / not tracked")
        lanes.append({
            "id": lid, "name": name, "lane_class": cls, "detected": bool(path or own or lid in secrets),
            "detection": (f"launcher {Path(path).name}" if path else "Studio route registry" if own
                          else "credential registered in provider store" if lid in secrets else "not found"),
            "readiness": readiness, "route_type": _route_type(cls, verified, routes),
            "route_id": verified[0] if verified else None, "verified_routes": verified,
            "conversation_support": conv, "cost_visibility": cost, "billing_note": billing,
            "counts_as_speaker": cls in ("admin", "speaker") and conv == "in_app_verified"
                                 and not (metered_only and not funded),
            "reasons": reasons})
    # anything registered in Studio or the secret store that the catalog doesn't know about
    known = {lid for lid, *_ in CATALOG}
    for rid, r in routes.items():
        if rid in claimed_routes:
            continue
        ready = r["state"] in ("READY_INCLUDED", "READY_METERED", "SIMULATED")
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


def _route_type(cls, verified, routes) -> str:
    if not verified:
        return {"research": "research tool", "review": "review tool"}.get(cls, "official CLI (not integrated)")
    kinds = sorted({"separately billed API" if routes[r]["billing_basis"] == "metered" else "official CLI · plan quota"
                    for r in verified})
    return " + ".join(kinds)
