"""Arena compare surface: demo catalog, cost estimates, and free-route dual-lane run.

v1 ships interactive demo fixtures plus per-lane provider/model pickers and cost
readouts. Live dual generation dispatches only when **both** lanes are included /
local / simulated (same rules as $0 estimates). Metered routes stay refused with a
clear note — nothing is reserved for a refused lane (see ledger / AGENTS.md).
Estimates never invent credentials; they only read cached route metadata and the
verified OpenAI price table when a metered Codex API route is selected.
"""
from __future__ import annotations

from . import openai_api, providers
from .store import Store

# Reference brief sizes (UTF-8 bytes) used only for estimate math — not sent anywhere.
DEMO_BRIEF_BYTES = {
    "alpine": 12_000,
    "lost-valley": 14_000,
    "deep-time": 11_000,
    "optical": 9_500,
}

DEMOS = (
    {
        "id": "alpine",
        "title": "Alpine Atlas",
        "subtitle": "Neuschwanstein field controls",
        "genre": "3D field atlas",
        "blurb": "Season, time of day, camera and mood controls over an alpine castle scene.",
    },
    {
        "id": "lost-valley",
        "title": "Lost Valley",
        "subtitle": "Dinosaur sanctuary habitat",
        "genre": "live habitat",
        "blurb": "Primeval sanctuary with habitat toggles and field controls.",
    },
    {
        "id": "deep-time",
        "title": "Deep Time Atlas",
        "subtitle": "Crocodiles + geologic timeline",
        "genre": "specimen timeline",
        "blurb": "Specimen card with a scrubbable geologic timeline.",
    },
    {
        "id": "optical",
        "title": "Optical Gallery",
        "subtitle": "Fieldwork vs UNSTILL landings",
        "genre": "gallery landing",
        "blurb": "Two optical-art gallery landing fixtures (lane A / lane B variants).",
    },
)


LIVE_NOTE = (
    "Run both dispatches two free-route chat turns (included / local / simulated) "
    "through the existing chat APIs. Metered lanes stay off until the owner sets a "
    "limit or permit — Arena never reserves ledger for a refused lane."
)

PROMPT_HEAD = (
    "Arena dual-lane compare (read-only chat, no tools, no file writes). "
    "Answer the brief below in at most 120 words.\n\n"
)

REFUSE_METERED = (
    "Arena Run both only allows included, local, or simulated lanes. "
    "Metered routes stay off until the owner sets a limit or permit; nothing was reserved."
)


def demos() -> list[dict]:
    return [dict(d) for d in DEMOS]


def _demo(demo_id: str) -> dict:
    for d in DEMOS:
        if d["id"] == demo_id:
            return d
    raise ValueError(f"unknown arena demo {demo_id!r}")


def lane_allows_live_dispatch(route: dict | None) -> bool:
    """True only for included / local / simulated routes (same rules as $0 estimates).

    Any METERED* state is refused even when billing_basis still says subscription_included
    (e.g. READY_METERED_DISABLED Codex CLI on API-key auth).
    """
    if not route:
        return False
    basis = route.get("billing_basis") or "unknown"
    state = route.get("state") or "UNKNOWN"
    if "METERED" in str(state):
        return False
    return (
        basis in ("subscription_included", "local")
        or state in ("READY_INCLUDED", "READY_LOCAL", "SIMULATED")
    )


def demo_prompt(demo_id: str, text: str | None = None) -> str:
    """Build the chat prompt for a dual-lane run from an optional owner brief or the demo catalog."""
    custom = (text or "").strip()
    if custom:
        return PROMPT_HEAD + custom
    demo = _demo(demo_id)
    brief = (
        f"Demo: {demo['title']} ({demo['subtitle']}). Genre: {demo['genre']}. "
        f"{demo['blurb']} Propose one concrete interaction idea for this demo."
    )
    return PROMPT_HEAD + brief


def _refuse_reason(route_id: str, route: dict | None) -> str:
    if not route:
        return f"unknown route {route_id!r}"
    state = route.get("state") or "UNKNOWN"
    basis = route.get("billing_basis") or "unknown"
    if "METERED" in str(state) or basis == "metered":
        return f"{route_id}: {REFUSE_METERED} (state={state}, billing_basis={basis})"
    return (
        f"{route_id}: not eligible for Arena live dispatch "
        f"(state={state}, billing_basis={basis})"
    )


def estimate(store: Store, route_id: str, demo_id: str) -> dict:
    """Return a non-binding cost readout for one lane. Never reserves or dispatches."""
    demo = _demo(demo_id)
    routes = providers.cached(store)
    route = routes.get(route_id)
    if not route:
        raise ValueError(f"unknown route {route_id!r}")
    basis = route.get("billing_basis") or "unknown"
    state = route.get("state") or "UNKNOWN"
    brief = DEMO_BRIEF_BYTES[demo_id]
    live = lane_allows_live_dispatch(route)
    out = {
        "route_id": route_id,
        "display_name": route.get("display_name") or providers.display_name(route_id),
        "demo_id": demo_id,
        "demo_title": demo["title"],
        "billing_basis": basis,
        "state": state,
        "estimate_usd": None,
        "estimate_kind": "unavailable",
        "currency": "USD",
        "note": "",
        "price_source": None,
        "live_dispatch": live,
        "brief_bytes": brief,
    }
    # READY_METERED_DISABLED can keep billing_basis="subscription_included" (e.g. Codex CLI on
    # API-key auth). Treat any METERED state as metered so estimates never report $0 for it.
    metered_state = "METERED" in str(state)
    if live:
        out.update(
            estimate_usd=0.0,
            estimate_kind="included_or_local",
            note="Plan quota or local compute — $0 provider spend for this estimate. "
                 "Eligible for Arena Run both when the other lane is also free.",
            price_source=route.get("incremental_cost_status") or basis,
        )
        return out
    if basis == "metered" or metered_state:
        # Only Codex API has a verified in-repo price table. Other metered routes stay honest.
        if route_id == "openai-api":
            model = openai_api.DEFAULT_MODEL
            try:
                usd = openai_api.max_cost(model, brief, openai_api.DEFAULT_MAX_OUTPUT)
            except openai_api.ApiError as e:
                out.update(estimate_kind="price_error", note=str(e), price_source=openai_api.PRICE_SOURCE)
                return out
            out.update(
                estimate_usd=usd,
                estimate_kind="metered_ceiling",
                note=f"Upper-bound reservation style estimate for {model} "
                     f"(~{brief:,} byte brief, {openai_api.DEFAULT_MAX_OUTPUT} max out). "
                     "Arena Run both refuses metered lanes; nothing is reserved.",
                price_source=openai_api.PRICE_SOURCE,
                model=model,
            )
            return out
        out.update(
            estimate_kind="metered_unknown",
            note="Metered route without a Studio-cached unit price for Arena estimates. "
                 "See Providers → Incremental cost. Arena Run both refuses metered lanes; nothing is reserved.",
            price_source=route.get("incremental_cost_status"),
        )
        return out
    out.update(
        estimate_kind="unavailable",
        note=route.get("incremental_cost_status") or f"No estimate for billing basis {basis!r}.",
        price_source=route.get("incremental_cost_status"),
    )
    return out


def compare_payload(store: Store, lane_a: str, lane_b: str, demo_id: str) -> dict:
    """Bundle demos list + both lane estimates for the Arena shell."""
    a = estimate(store, lane_a, demo_id)
    b = estimate(store, lane_b, demo_id)
    both = bool(a.get("live_dispatch") and b.get("live_dispatch"))
    return {
        "demos": demos(),
        "demo_id": demo_id,
        "lanes": {"a": a, "b": b},
        "live_dual_generation": both,
        "live_note": LIVE_NOTE if both else (
            LIVE_NOTE + " Pick two included/local/simulated lanes to enable Run both."
        ),
    }


def run_both(store: Store, svc, project_id: str, lane_a: str, lane_b: str,
             demo_id: str, text: str | None = None) -> dict:
    """Dispatch two free-route chat turns via existing Services.send. Never reserves for refused lanes.

    Raises ValueError with a clear reason when either lane fails eligibility or chat usability.
    """
    svc.project(project_id)
    _demo(demo_id)  # validate demo id early
    routes = providers.cached(store)
    checks: list[tuple[str, str, dict | None]] = [
        ("a", lane_a, routes.get(lane_a)),
        ("b", lane_b, routes.get(lane_b)),
    ]
    for side, rid, route in checks:
        if not rid:
            raise ValueError(f"lane {side}: route id is required")
        if not lane_allows_live_dispatch(route):
            raise ValueError(_refuse_reason(rid, route))
        if not providers.usable(route, "chat"):
            state = (route or {}).get("state") or "UNKNOWN"
            raise ValueError(f"{rid}: route not usable for chat (state={state})")

    prompt = demo_prompt(demo_id, text)
    lanes_out: dict[str, dict] = {}
    for side, rid, _route in checks:
        conv = svc.new_conversation(project_id, title=f"Arena {side.upper()} · {demo_id}")
        sent = svc.send(project_id, conv["id"], prompt, [], rid)
        lanes_out[side] = {
            "route_id": rid,
            "conversation_id": conv["id"],
            "message_id": sent["message_id"],
            "task_id": sent["task_id"],
        }
    return {
        "demo_id": demo_id,
        "prompt_chars": len(prompt),
        "lanes": lanes_out,
        "live_dual_generation": True,
        "live_note": LIVE_NOTE,
    }
