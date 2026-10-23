"""Atomic spend ledger. OpenAI is the only permitted new biller.

Two separate envelopes, never mixed:
- mission:  development/integration spend, $165 aggregate ceiling, needs the mission permit
            (forced off at every server start; the owner turns it on deliberately).
- runtime:  everyday metered use, disabled until the owner sets a monthly operating limit.

Subscription-included routes are recorded as quota usage at $0 - never converted into
fabricated API dollars. Before every metered dispatch:
settled + outstanding exposure + next maximum reservation <= envelope ceiling.
"""
from __future__ import annotations

import time

from .store import Store, new_id

CEILING_USD = 165.0
ALLOWED_BILLERS = {"openai"}
FREEZE_OPTIONAL_AT = 120.0
PRIORITIZE_CORE_AT = 145.0


class BudgetError(RuntimeError):
    pass


def _kv(store: Store, k: str) -> str | None:
    row = store.one("SELECT v FROM kv WHERE k=?", (k,))
    return row["v"] if row else None


def _set_kv(store: Store, k: str, v: str) -> None:
    store.x("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))


def permit_enabled(store: Store) -> bool:
    return _kv(store, "billable_permit") == "on"


def set_permit(store: Store, on: bool) -> None:
    _set_kv(store, "billable_permit", "on" if on else "off")


def runtime_limit(store: Store) -> float:
    try:
        return max(0.0, float(_kv(store, "runtime_limit_usd") or 0))
    except ValueError:
        return 0.0


def set_runtime_limit(store: Store, usd: float) -> None:
    if usd < 0 or usd > 1000:
        raise BudgetError("monthly operating limit must be between $0 and $1000")
    _set_kv(store, "runtime_limit_usd", f"{usd:.2f}")


def _month_start() -> float:
    t = time.localtime()
    return time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, -1))


def _envelope(c, purpose: str) -> tuple[float, float]:
    """(settled, outstanding) for an envelope, read inside the caller's transaction."""
    since = _month_start() if purpose == "runtime" else 0
    settled = c.execute("SELECT COALESCE(SUM(settled_usd),0) FROM ledger WHERE status='settled' AND purpose=? "
                        "AND created>=?", (purpose, since)).fetchone()[0]
    outstanding = c.execute("SELECT COALESCE(SUM(reservation_usd),0) FROM ledger WHERE status IN "
                            "('reserved','ambiguous') AND purpose=? AND created>=?", (purpose, since)).fetchone()[0]
    return settled, outstanding


def active_purpose(store: Store) -> str | None:
    """Which envelope a metered call would bill: mission permit first, else a configured runtime limit."""
    if permit_enabled(store):
        return "mission"
    if runtime_limit(store) > 0:
        return "runtime"
    return None


def resolve(store: Store, ledger_id: str, actual_usd: float, note: str = "") -> None:
    """Owner action: settle an ambiguous (cancelled/timed-out) reservation from the provider's usage dashboard."""
    if not (0 <= actual_usd <= 1000):
        raise BudgetError("resolved amount must be between $0 and $1000")
    row = store.one("SELECT status FROM ledger WHERE id=?", (ledger_id,))
    if not row:
        raise KeyError("ledger entry not found")
    if row["status"] != "ambiguous":
        raise BudgetError("only unresolved (ambiguous) exposure can be resolved")
    settle(store, ledger_id, actual_usd)
    store.event("exposure_resolved", None, ledger_id=ledger_id, actual=actual_usd, note=note[:200])


def totals(store: Store) -> dict:
    with store.conn() as c:
        ms, mo = _envelope(c, "mission")
        rs, ro = _envelope(c, "runtime")
        amb = c.execute("SELECT COALESCE(SUM(reservation_usd),0) FROM ledger WHERE status='ambiguous' "
                        "AND purpose='mission'").fetchone()[0]
        included = c.execute("SELECT count(*) FROM ledger WHERE billing_basis='subscription_included'").fetchone()[0]
        calls = c.execute("SELECT count(*) FROM ledger WHERE billing_basis='metered'").fetchone()[0]
    committed = ms + mo
    lim = runtime_limit(store)
    return {"ceiling": CEILING_USD, "settled": round(ms, 6), "outstanding": round(mo, 6), "ambiguous": round(amb, 6),
            "committed": round(committed, 6), "remaining": round(CEILING_USD - committed, 6),
            "included_uses": included, "metered_calls": calls, "permit": permit_enabled(store),
            "runtime_limit": lim, "runtime_month_settled": round(rs, 6), "runtime_month_outstanding": round(ro, 6),
            "runtime_month_remaining": round(lim - rs - ro, 6),
            "phase": ("prioritize_core" if committed >= PRIORITIZE_CORE_AT else
                      "freeze_optional" if committed >= FREEZE_OPTIONAL_AT else "normal")}


def reserve(store: Store, provider: str, route: str, billing_basis: str, amount_usd: float | None,
            task_ref: str | None = None, price_source: str | None = None, purpose: str | None = None) -> str:
    """Reserve exposure before dispatch. Raises BudgetError when the dispatch is not allowed."""
    if billing_basis == "subscription_included":
        lid = new_id("led")
        store.x("INSERT INTO ledger(id,provider,route,billing_basis,task_ref,reservation_usd,settled_usd,status,"
                "price_source,created,purpose) VALUES(?,?,?,?,?,0,0,'reserved',?,?,'included')",
                (lid, provider, route, billing_basis, task_ref, price_source or "subscription quota", time.time()))
        return lid
    if billing_basis != "metered":
        raise BudgetError(f"unknown billing basis {billing_basis!r}")
    if provider not in ALLOWED_BILLERS:
        raise BudgetError(f"{provider} is not an authorized biller; incremental spend must be $0")
    if amount_usd is None or amount_usd <= 0:
        raise BudgetError("metered dispatch needs a bounded positive maximum reservation")
    with store.tx() as c:
        on = c.execute("SELECT v FROM kv WHERE k='billable_permit'").fetchone()
        lim_row = c.execute("SELECT v FROM kv WHERE k='runtime_limit_usd'").fetchone()
        lim = float(lim_row[0]) if lim_row else 0.0
        if purpose is None:
            purpose = "mission" if on and on[0] == "on" else "runtime" if lim > 0 else None
        if purpose == "mission":
            if not on or on[0] != "on":
                raise BudgetError("mission billable permit is disabled")
            ceiling = CEILING_USD
        elif purpose == "runtime":
            if lim <= 0:
                raise BudgetError("metered everyday use is disabled until the owner sets a monthly operating limit")
            ceiling = lim
        else:
            raise BudgetError("metered route disabled: mission permit off and no monthly operating limit set")
        settled, outstanding = _envelope(c, purpose)
        if settled + outstanding + amount_usd > ceiling + 1e-9:
            raise BudgetError(f"reservation ${amount_usd:.4f} would exceed the {purpose} ceiling ${ceiling:.2f} "
                              f"(settled ${settled:.4f} + outstanding ${outstanding:.4f})")
        lid = new_id("led")
        c.execute("INSERT INTO ledger(id,provider,route,billing_basis,task_ref,reservation_usd,status,price_source,"
                  "created,purpose) VALUES(?,?,?,?,?,?,'reserved',?,?,?)",
                  (lid, provider, route, billing_basis, task_ref, amount_usd, price_source, time.time(), purpose))
    return lid


def settle(store: Store, ledger_id: str, actual_usd: float | None) -> None:
    """Settle a reservation. actual_usd=None means the outcome is unknown: keep exposure as ambiguous.
    An actual charge above its reservation is recorded as billed and flagged, never hidden."""
    if actual_usd is not None:
        row = store.one("SELECT reservation_usd, purpose FROM ledger WHERE id=?", (ledger_id,))
        if row and row["reservation_usd"] and actual_usd > row["reservation_usd"] + 1e-12:
            store.event("reservation_overshoot", None, ledger_id=ledger_id, purpose=row["purpose"],
                        reserved=row["reservation_usd"], actual=actual_usd)
    if actual_usd is None:
        store.x("UPDATE ledger SET status='ambiguous' WHERE id=? AND status='reserved'", (ledger_id,))
    else:
        store.x("UPDATE ledger SET status='settled', settled_usd=?, settled=? WHERE id=? AND status IN "
                "('reserved','ambiguous')", (actual_usd, time.time(), ledger_id))
