"""Aesop prompt generator: offline idea → structured prompt scaffolds for Chat / Plan / Research.

Inspired by public prompt-generator *abilities* (modes, ready vs reusable, variables, model targeting),
implemented as Studio-owned scaffolds. No third-party brand, copy, assets, or network calls.
Default generation spends $0. Optional enhance uses only already-usable included/local/simulated chat routes.
"""
from __future__ import annotations

import json
import re
import time

from . import providers
from .security import redact
from .tasks import TERMINAL

MODES = (
    "auto",
    "general",
    "research",
    "writing",
    "planning",
    "agent",
    "image",
    "video",
    "code",
    "automation",
)

LANGUAGES = (
    ("en", "English"),
    ("id", "Bahasa Indonesia"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("pt", "Portuguese"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("zh", "Chinese"),
)

OUTPUT_KINDS = ("ready", "reusable")

# Role + section hints per mode (Aesop wording).
_MODE_META = {
    "auto": ("capable assistant", "Infer the best structure for the brief."),
    "general": ("general assistant", "Answer clearly with steps when useful."),
    "research": ("research analyst", "Prioritize sources, uncertainty, and citations."),
    "writing": ("writing partner", "Match voice, audience, and deliverable shape."),
    "planning": ("planning partner", "Break work into ordered, verifiable steps."),
    "agent": ("software agent", "Act only within stated tools and stop conditions."),
    "image": ("image prompt specialist", "Describe subject, composition, style, and exclusions."),
    "video": ("video prompt specialist", "Describe shot, motion, timing, and audio cues."),
    "code": ("software engineer", "Prefer correct, testable changes with clear acceptance checks."),
    "automation": ("automation designer", "Specify triggers, inputs, steps, and failure handling."),
}

_VAR_RE = re.compile(r"\{([a-z][a-z0-9_]{0,39})\}")
MAX_IDEA = 4000
MAX_FIELD = 2000
# Fits a full generate() scaffold (max idea + four fields + section labels), not a silent 8k cut.
MAX_PROMPT = MAX_IDEA + 4 * MAX_FIELD + 2048
ENHANCE_TIMEOUT = 120
ENHANCE_PREFERRED = (
    "simulated", "claude", "codex", "cursor", "antigravity",
    "director-lmstudio", "director-ollama",
)

# Studio routes preferred when target is universal / by mode family.
_ROUTE_HINTS = {
    "research": ("perplexity-orchestrator", "perplexity", "claude", "codex", "cursor", "antigravity"),
    "code": ("codex", "claude", "cursor", "antigravity", "simulated"),
    "agent": ("codex", "claude", "cursor", "antigravity", "simulated"),
    "writing": ("claude", "codex", "cursor", "antigravity"),
    "planning": ("claude", "codex", "cursor", "antigravity"),
    "image": ("openai-api", "claude", "codex"),
    "video": ("openai-api", "claude", "codex"),
    "automation": ("codex", "claude", "cursor", "antigravity"),
    "general": ("claude", "codex", "cursor", "antigravity", "simulated"),
    "auto": ("claude", "codex", "cursor", "antigravity", "simulated"),
}


def schema() -> dict:
    return {
        "modes": [{"id": m, "label": m.replace("_", " ").title(), "hint": _MODE_META[m][1]} for m in MODES],
        "languages": [{"id": i, "label": lab} for i, lab in LANGUAGES],
        "output_kinds": [
            {"id": "ready", "label": "Ready to use", "hint": "Complete prompt for one task"},
            {"id": "reusable", "label": "Reusable template", "hint": "Keep {variables} for later fills"},
        ],
        "targets": [
            {"id": "universal", "label": "Universal (portable)"},
            {"id": "studio", "label": "Recommend Studio routes"},
        ],
        "spend": "Offline generate is always free. Enhance only uses included/local/simulated chat routes.",
    }


def _clean(text: str, limit: int) -> str:
    """Trim only surrounding whitespace; keep internal newlines/indentation (fenced code, YAML).

    Oversized input is rejected (not truncated) so enhance never drops the tail of a valid scaffold.
    """
    out = (text or "").strip()
    if len(out) > limit:
        raise ValueError(f"text exceeds {limit} characters ({len(out)} given)")
    return out


def _lang_label(code: str) -> str:
    for i, lab in LANGUAGES:
        if i == code:
            return lab
    raise ValueError("unknown output language")


def _infer_mode(idea: str) -> str:
    low = idea.lower()
    checks = (
        ("image", ("image", "illustration", "midjourney", "photo of", "render a")),
        ("video", ("video", "clip", "cinematic shot", "timelapse")),
        ("code", ("code", "refactor", "unit test", "pull request", "bugfix", "typescript", "python")),
        ("research", ("research", "cite", "sources", "literature", "compare vendors")),
        ("planning", ("plan", "roadmap", "milestone", "checklist", "schedule")),
        ("agent", ("agent", "tool use", "browser", "automate in the repo")),
        ("automation", ("workflow", "trigger", "cron", "pipeline", "zap")),
        ("writing", ("blog", "essay", "rewrite", "tone", "draft an email")),
    )
    for mode, words in checks:
        if any(w in low for w in words):
            return mode
    return "general"


def _variables(*parts: str) -> list[dict]:
    seen: list[str] = []
    for part in parts:
        for name in _VAR_RE.findall(part or ""):
            if name not in seen:
                seen.append(name)
    return [{"name": n, "example": f"fill {n.replace('_', ' ')}"} for n in seen]


def _estimate_tokens(text: str) -> dict:
    # Rough local estimate only (not a billing meter).
    n = max(1, len(text) // 4)
    return {"input": n, "output": max(80, n // 2), "note": "local character heuristic, not provider billing"}


def recommend_routes(store, mode: str) -> list[dict]:
    routes = providers.cached(store)
    prefer = _ROUTE_HINTS.get(mode, _ROUTE_HINTS["auto"])
    out = []
    for rid in prefer:
        r = routes.get(rid)
        if not r:
            continue
        if not providers.usable(r, "chat"):
            continue
        out.append({
            "id": rid,
            "display_name": providers.display_name(rid),
            "state": r.get("state"),
            "incremental_cost_status": r.get("incremental_cost_status"),
        })
        if len(out) >= 4:
            break
    if not out:
        for rid, r in routes.items():
            if providers.usable(r, "chat"):
                out.append({
                    "id": rid,
                    "display_name": providers.display_name(rid),
                    "state": r.get("state"),
                    "incremental_cost_status": r.get("incremental_cost_status"),
                })
            if len(out) >= 3:
                break
    return out


def _enhance_ok(route: dict) -> bool:
    """Metered chat stays off until the owner enables limits/permit elsewhere; enhance never bills."""
    return bool(route) and providers.usable(route, "chat") and route.get("state") in (
        "READY_INCLUDED", "READY_LOCAL", "SIMULATED",
    )


def _pick_enhance_route(routes: dict, preferred: str | None = None) -> str | None:
    """Prefer an explicit/project route, then ENHANCE_PREFERRED, then any other eligible cached route."""
    if preferred and preferred in routes and _enhance_ok(routes[preferred]):
        return preferred
    for rid in ENHANCE_PREFERRED:
        if rid in routes and _enhance_ok(routes[rid]):
            return rid
    for rid, route in routes.items():
        if rid not in ENHANCE_PREFERRED and _enhance_ok(route):
            return rid
    return None


def _project_for_enhance(project: dict, route: str) -> dict:
    """Drop a foreign model pin when enhance switches away from the project's default provider."""
    out = dict(project)
    if route != project.get("provider_default"):
        out.pop("model", None)
    return out


def generate(
    store,
    pid: str,
    *,
    idea: str,
    mode: str = "auto",
    target: str = "universal",
    language: str = "en",
    output_kind: str = "ready",
    audience: str = "",
    output_format: str = "",
    constraints: str = "",
    context: str = "",
) -> dict:
    idea = _clean(idea, MAX_IDEA)
    if len(idea) < 4:
        raise ValueError("describe what you want the prompt to accomplish")
    if mode not in MODES:
        raise ValueError("unknown mode")
    if output_kind not in OUTPUT_KINDS:
        raise ValueError("output_kind must be ready or reusable")
    if target not in ("universal", "studio"):
        raise ValueError("target must be universal or studio")
    lang = _lang_label(language)
    audience = _clean(audience, MAX_FIELD)
    output_format = _clean(output_format, MAX_FIELD)
    constraints = _clean(constraints, MAX_FIELD)
    context = _clean(context, MAX_FIELD)

    resolved = _infer_mode(idea) if mode == "auto" else mode
    role, hint = _MODE_META[resolved]

    if output_kind == "reusable":
        goal = "{goal}"
        aud = audience or "{audience}"
        fmt = output_format or "{output_format}"
        cons = constraints or "{constraints}"
        ctx = context or "{context}"
        title_bit = "{title}"
    else:
        goal = idea
        aud = audience or "the owner of this Aesop Studio project"
        fmt = output_format or "clear prose with headings when helpful"
        cons = constraints or "stay factual; say when something is unknown"
        ctx = context or "Use only the project context the user provides in this chat."
        title_bit = idea[:72]

    sections = [
        f"You are a {role}.",
        "",
        f"Goal:\n{goal}",
        "",
        f"Audience:\n{aud}",
        "",
        f"Context:\n{ctx}",
        "",
        f"Instructions:\n- {hint}\n- Prefer concrete, checkable results.\n- Ask for missing inputs only when blocked.",
        "",
        f"Constraints:\n{cons}",
        "",
        f"Expected output:\n{fmt}",
        "",
        f"Output language: {lang}.",
    ]
    if target == "universal":
        sections.append("Model target: portable across capable chat models.")
    else:
        sections.append("Model target: prefer a Studio route listed under recommended_routes.")

    prompt = redact("\n".join(sections).strip())
    title = redact(f"{resolved.title()} prompt — {title_bit}"[:120])
    variables = _variables(prompt) if output_kind == "reusable" else []
    recommended = recommend_routes(store, resolved) if target in ("universal", "studio") else []
    usage_notes = [
        "Review before sending to a provider.",
        "Offline scaffold only; wording is Aesop's, not a third-party clone.",
    ]
    if variables:
        usage_notes.append("Replace {variables} before use, or keep as a reusable template.")

    result = {
        "title": title,
        "prompt": prompt,
        "mode": resolved,
        "mode_requested": mode,
        "target": target,
        "language": language,
        "output_kind": output_kind,
        "variables": variables,
        "recommended_routes": recommended,
        "usage_notes": usage_notes,
        "token_estimate": _estimate_tokens(prompt),
        "context_summary": redact((context or idea)[:240]),
        "spend": "none",
    }
    store.event(
        "prompt_generator",
        pid,
        mode=resolved,
        output_kind=output_kind,
        target=target,
        language=language,
        chars=len(prompt),
    )
    return result


def enhance(store, sup, svc, pid: str, prompt: str, provider: str | None = None) -> dict:
    """Optional polish via an included/local/simulated chat route. Never uses metered billing."""
    prompt = redact(_clean(prompt, MAX_PROMPT))
    if len(prompt) < 20:
        raise ValueError("paste a prompt to enhance first")
    p = svc.project(pid)
    routes = providers.cached(store)
    route = _pick_enhance_route(routes, provider or p.get("provider_default"))
    if not route:
        raise ValueError(
            "enhance needs an included, local, or simulated chat route; "
            "metered routes stay off until the owner sets a limit or permit"
        )
    instruction = (
        "Improve the following prompt for clarity, constraints, and expected output. "
        "Return ONLY the improved prompt text. Do not add commentary.\n\n"
        f"PROMPT:\n{prompt}"
    )
    # Supervisor.create forwards project["model"] into build_argv; a Claude opus pin must not
    # follow the call onto director-lmstudio / another route that rejects foreign models.
    tid = sup.create(_project_for_enhance(p, route), route, instruction, mode="chat",
                     timeout=ENHANCE_TIMEOUT)
    end = time.time() + ENHANCE_TIMEOUT + 30
    while time.time() < end:
        t = sup.final(tid)
        if t["state"] in TERMINAL and not json.loads(t["checkpoint"] or "{}").get("retried_as"):
            break
        time.sleep(0.4)
    t = sup.final(tid)
    if t["state"] != "COMPLETED":
        raise ValueError(f"enhance ended {t['state'].lower()}: {(t['error'] or '')[:160]}")
    text = (json.loads(t["checkpoint"] or "{}").get("result") or sup.output(t["id"])[0]).strip()
    text = redact(text)
    store.event("prompt_generator_enhance", pid, provider=route, chars=len(text))
    return {
        "prompt": text,
        "provider": providers.display_name(route),
        "route": route,
        "variables": _variables(text),
        "token_estimate": _estimate_tokens(text),
        "spend": "included_or_simulated",
    }
