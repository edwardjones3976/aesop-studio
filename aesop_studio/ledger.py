"""Atomic mission ledger. OpenAI is the only permitted new biller; $165 aggregate ceiling.

Subscription-included routes are recorded as quota usage at $0 - never converted into
fabricated API dollars. Metered routes need the mission permit, a bounded reservation and
must satisfy: settled + outstanding exposure + next reservation <= ceiling.
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


def permit_enabled(store: Store) -> bool:
    row = store.one("SELECT v FROM kv WHERE k='billable_permit'")
    return bool(row and row["v"] == "on")


def set_permit(store: Store, on: bool) -> None:
    store.x("INSERT INTO kv(k,v) VALUES('billable_permit',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            ("on" if on else "off",))


def totals(store: Store) -> dict:
    rows = store.q("SELECT billing_basis,status,reservation_usd,settled_usd FROM ledger")
    settled = sum(r["settled_usd"] or 0 for r in rows if r["status"] == "settled")
    outstanding = sum(r["reservation_usd"] for r in rows if r["status"] in ("reserved", "ambiguous"))
    ambiguous = sum(r["reservation_usd"] for r in rows if r["status"] == "ambiguous")
    included = sum(1 for r in rows if r["billing_basis"] == "subscription_included")
    committed = settled + outstanding
    return {"ceiling": CEILING_USD, "settled": round(settled, 4), "outstanding": round(outstanding, 4),
            "ambiguous": round(ambiguous, 4), "committed": round(committed, 4),
            "remaining": round(CEILING_USD - committed, 4), "included_uses": included,
            "permit": permit_enabled(store),
            "phase": ("prioritize_core" if committed >= PRIORITIZE_CORE_AT else
                      "freeze_optional" if committed >= FREEZE_OPTIONAL_AT else "normal")}


def reserve(store: Store, provider: str, route: str, billing_basis: str, amount_usd: float | None,
            task_ref: str | None = None, price_source: str | None = None) -> str:
    """Reserve exposure before dispatch. Raises BudgetError when the dispatch is not allowed."""
    if billing_basis == "subscription_included":
        lid = new_id("led")
        store.x("INSERT INTO ledger(id,provider,route,billing_basis,task_ref,reservation_usd,settled_usd,status,"
                "price_source,created) VALUES(?,?,?,?,?,0,0,'reserved',?,?)",
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
        if not on or on[0] != "on":
            raise BudgetError("mission billable permit is disabled")
        settled = c.execute("SELECT COALESCE(SUM(settled_usd),0) FROM ledger WHERE status='settled'").fetchone()[0]
        outstanding = c.execute("SELECT COALESCE(SUM(reservation_usd),0) FROM ledger "
                                "WHERE status IN ('reserved','ambiguous')").fetchone()[0]
        if settled + outstanding + amount_usd > CEILING_USD + 1e-9:
            raise BudgetError(f"reservation ${amount_usd:.2f} would exceed ceiling "
                              f"(settled ${settled:.2f} + outstanding ${outstanding:.2f})")
        lid = new_id("led")
        c.execute("INSERT INTO ledger(id,provider,route,billing_basis,task_ref,reservation_usd,status,price_source,"
                  "created) VALUES(?,?,?,?,?,?,'reserved',?,?)",
                  (lid, provider, route, billing_basis, task_ref, amount_usd, price_source, time.time()))
    return lid


def settle(store: Store, ledger_id: str, actual_usd: float | None) -> None:
    """Settle a reservation. actual_usd=None means the outcome is unknown: keep exposure as ambiguous."""
    if actual_usd is None:
        store.x("UPDATE ledger SET status='ambiguous' WHERE id=? AND status='reserved'", (ledger_id,))
    else:
        store.x("UPDATE ledger SET status='settled', settled_usd=?, settled=? WHERE id=? AND status IN "
                "('reserved','ambiguous')", (actual_usd, time.time(), ledger_id))
