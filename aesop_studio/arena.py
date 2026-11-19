"""Arena compare surface: demo catalog and read-only cost estimates.

v1 ships interactive demo fixtures plus per-lane provider/model pickers and cost
readouts. Live dual generation is intentionally not dispatched here — metered
routes stay off until the owner sets a limit or permit (see ledger / AGENTS.md).
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
    "Arena v1 ships demos, provider swap and cost UI only. "
    "Live dual generation waits on existing chat/task APIs and owner metered limits."
)


def demos() -> list[dict]:
    return [dict(d) for d in DEMOS]


def _demo(demo_id: str) -> dict:
    for d in DEMOS:
        if d["id"] == demo_id:
            return d
    raise ValueError(f"unknown arena demo {demo_id!r}")


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
        "live_dispatch": False,
        "brief_bytes": brief,
    }
    if basis in ("subscription_included", "local") or state in ("READY_INCLUDED", "READY_LOCAL", "SIMULATED"):
        out.update(
            estimate_usd=0.0,
            estimate_kind="included_or_local",
            note="Plan quota or local compute — $0 provider spend for this estimate. Live dual-run is off in Arena v1.",
            price_source=route.get("incremental_cost_status") or basis,
        )
        return out
    if basis == "metered" or "METERED" in str(state):
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
                     "Arena v1 does not dispatch; nothing is reserved.",
                price_source=openai_api.PRICE_SOURCE,
                model=model,
            )
            return out
        out.update(
            estimate_kind="metered_unknown",
            note="Metered route without a Studio-cached unit price for Arena estimates. "
                 "See Providers → Incremental cost. Arena v1 does not dispatch or reserve.",
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
    return {
        "demos": demos(),
        "demo_id": demo_id,
        "lanes": {
            "a": estimate(store, lane_a, demo_id),
            "b": estimate(store, lane_b, demo_id),
        },
        "live_dual_generation": False,
        "live_note": LIVE_NOTE,
    }
