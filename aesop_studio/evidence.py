"""One shared evidence model feeding the live dashboard, the HTML report and JSON exports."""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from . import ledger, providers
from .store import Store

ACCEPTANCE_FILE = Path(__file__).resolve().parent.parent / "docs" / "acceptance.json"


def acceptance() -> list[dict]:
    try:
        return json.loads(ACCEPTANCE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def collect(store: Store) -> dict:
    tasks = store.q("SELECT id,provider,state,created,started,ended,checkpoint FROM tasks")
    by_state: dict[str, int] = {}
    for t in tasks:
        by_state[t["state"]] = by_state.get(t["state"], 0) + 1
    samples: dict[str, list[float]] = {}
    for t in tasks:
        if t["state"] == "COMPLETED" and t["started"] and t["ended"]:
            mode = json.loads(t["checkpoint"] or "{}").get("mode", "?")
            samples.setdefault(f"{t['provider']}/{mode}", []).append(t["ended"] - t["started"])
    latency = [{"route": k, "n": len(v), "median_s": round(statistics.median(v), 2),
                "min_s": round(min(v), 2), "max_s": round(max(v), 2),
                "samples": [round(x, 2) for x in v[-10:]]} for k, v in sorted(samples.items())]
    recon = store.q("SELECT data,created FROM events WHERE kind='task_state' AND (data LIKE '%INTERRUPTED%' "
                    "OR data LIKE '%EFFECT_UNKNOWN%')")
    routes = providers.cached(store)
    workflow = store.q("SELECT data,created FROM events WHERE kind='workflow_measure' ORDER BY created")
    period = store.one("SELECT MIN(created) a, MAX(created) b FROM tasks")
    return {
        "generated_at": time.time(),
        "budget": ledger.totals(store),
        "ledger": store.q("SELECT id,provider,route,billing_basis,purpose,reservation_usd,settled_usd,status,created "
                          "FROM ledger ORDER BY created DESC LIMIT 50"),
        "allocation": [
            {"envelope": "Audit, research, foundation, visual direction", "cap": 18},
            {"envelope": "Project workspace and provider access", "cap": 46},
            {"envelope": "Official-agent supervision and recovery", "cap": 26},
            {"envelope": "Project memory and research notebook", "cap": 22},
            {"envelope": "HTML evidence and dashboard", "cap": 12},
            {"envelope": "Regression, security, backup/restore, review", "cap": 26},
            {"envelope": "Central repair reserve", "cap": 15}],
        "acceptance": acceptance(),
        "tasks": {"total": len(tasks), "by_state": by_state, "reconciliations": len(recon),
                  "period": period, "repairs": store.q("SELECT * FROM repairs ORDER BY created DESC")},
        "latency": latency,
        "workflow": [dict(json.loads(w["data"]), at=w["created"]) for w in workflow],
        "routes": [{"id": k, **{f: v.get(f) for f in ("provider", "state", "version", "billing_basis",
                                                       "incremental_cost_status", "evidence", "limitations")}}
                   for k, v in routes.items()],
        "research": json.loads((Path(__file__).resolve().parent.parent / "docs" / "research.json")
                               .read_text(encoding="utf-8")) if (Path(__file__).resolve().parent.parent / "docs" /
                                                                 "research.json").exists() else [],
    }
