"""Generate docs/report.html (self-contained, no remote assets) from the shared evidence model."""
from __future__ import annotations

import argparse
import html
import json
import os
import time
from pathlib import Path

from . import evidence
from .store import Store

DOCS = Path(__file__).resolve().parent.parent / "docs"
CSS = """:root{--bg:#f6f3ee;--panel:#fffdf9;--ink:#1f1c18;--muted:#6b645b;--line:#e3ddd3;--ok:#276749;--okb:#e3f4ea;
--warn:#8a5a00;--warnb:#fff4dc;--bad:#9b2c2c;--badb:#fde8e8}
@media (prefers-color-scheme:dark){:root{--bg:#161513;--panel:#1f1d1a;--ink:#ece7df;--muted:#a39b8f;--line:#36322c;
--ok:#8fd3ad;--okb:#1b3326;--warn:#f0c36a;--warnb:#3a2f17;--bad:#f19a9a;--badb:#3b1f1f}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 "Segoe UI",system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 60px}h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:28px 0 8px}
.muted{color:var(--muted)}.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px;background:var(--panel)}
caption{text-align:left;color:var(--muted);font-size:12px;padding:4px 0}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted)}.pill{font-size:11px;font-weight:700;padding:1px 8px;border-radius:99px}.ok{background:var(--okb);color:var(--ok)}
.warn{background:var(--warnb);color:var(--warn)}.bad{background:var(--badb);color:var(--bad)}.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 16px;margin:10px 0}
@media print{body{background:#fff}}"""


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def pill(s: str) -> str:
    cls = "ok" if s.startswith("PASS") or s in ("READY_INCLUDED", "COMPLETED") else \
          "bad" if s.startswith(("FAIL", "BLOCK")) else "warn"
    return f'<span class="pill {cls}">{esc(s)}</span>'


def table(caption: str, headers: list[str], rows: list[list[str]]) -> str:
    th = "".join(f"<th scope=col>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) or \
        f'<tr><td colspan={len(headers)} class=muted>No records.</td></tr>'
    return f'<div class=wrap><table><caption>{esc(caption)}</caption><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def build(ev: dict, notes: dict) -> str:
    b = ev["budget"]
    parts = [f"<h1>Aesop Studio: completion report</h1><p class=muted>Generated {esc(time.strftime('%Y-%m-%d %H:%M'))} "
             f"from the live evidence store. Mission status: <strong>{esc(notes.get('status', ''))}</strong>.</p>"]
    parts.append(f"<div class=card>{notes.get('summary_html', '')}</div>")
    parts.append("<h2>Budget ledger</h2>" + table("Mission spend, USD. Allocation is not expenditure.", ["Measure", "Value"], [
        [esc(k), esc(v)] for k, v in [("Ceiling", f"${b['ceiling']:.2f}"), ("Settled (billed)", f"${b['settled']:.2f}"),
                                      ("Outstanding reservations", f"${b['outstanding']:.2f}"),
                                      ("Unresolved exposure", f"${b['ambiguous']:.2f}"),
                                      ("Subscription-included runs ($0 incremental)", b["included_uses"]),
                                      ("Billable permit", "ON" if b["permit"] else "off (disabled at completion)")]]))
    parts.append(table("Planning envelopes: caps, not costs", ["Envelope", "Cap", "Spent"],
                       [[esc(a["envelope"]), f"${a['cap']}", "$0.00"] for a in ev["allocation"]]))
    parts.append("<h2>Acceptance matrix</h2>" + table("Requirement → implementation → test → status → evidence",
                 ["ID", "Requirement", "Implementation", "Test", "Status", "Evidence"],
                 [[esc(a["id"]), esc(a["requirement"]), esc(a["implementation"]), esc(a["test"]), pill(a["status"]),
                   esc(a["evidence"])] for a in ev["acceptance"]]))
    parts.append("<h2>Provider routes</h2>" + table("Verified through each official CLI's own status command",
                 ["Route", "Family", "State", "Version", "Billing", "Incremental", "Evidence"],
                 [[esc(r.get("display_name") or r["id"]), esc(r.get("family") or r["provider"]), pill(r["state"]), esc(r["version"]), esc(r["billing_basis"]),
                   esc(r["incremental_cost_status"]), esc(r["evidence"])] for r in ev["routes"]]))
    t = ev["tasks"]
    parts.append("<h2>Task success and recovery</h2>" + table(
        f"{t['total']} recorded run(s) in the evidence store at generation time", ["State", "Count"],
        [[pill(k), esc(v)] for k, v in sorted(t["by_state"].items())]))
    parts.append("<h2>Latency</h2>" + table("Provider wait (process start → exit). Individual samples, no confidence claims.",
                 ["Route/mode", "n", "Median s", "Samples"],
                 [[esc(l["route"]), esc(l["n"]), esc(l["median_s"]), esc(", ".join(map(str, l["samples"])))]
                  for l in ev["latency"]]))
    parts.append("<h2>Live verification log</h2>" + table("Real runs on this Windows host", ["Check", "Result"],
                 [[esc(k), esc(v)] for k, v in notes.get("live", [])]))
    parts.append("<h2>Independent review</h2>" + notes.get("review_html", "<p class=muted>Not recorded.</p>"))
    parts.append("<h2>Research background</h2>" + table("External sources are background, not Aesop Studio results",
                 ["Source", "Result", "Limitations", "Decision"],
                 [[f'<a href="{esc(r["url"])}">{esc(r["source"])}</a>', esc(r["result"]), esc(r["limitations"]),
                   esc(r["decision"])] for r in ev["research"]]))
    parts.append("<h2>Next highest-value action</h2>" + f"<p>{notes.get('next_html', '')}</p>")
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,"
            f"initial-scale=1'><title>Aesop Studio Report</title><style>{CSS}</style></head><body><main>"
            + "".join(parts) + "</main></body></html>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--notes", default=str(DOCS / "report-notes.json"))
    a = ap.parse_args()
    store = Store(a.data)
    ev = evidence.collect(store)
    notes = json.loads(Path(a.notes).read_text(encoding="utf-8")) if os.path.exists(a.notes) else {}
    (DOCS / "report.html").write_text(build(ev, notes), encoding="utf-8")
    (DOCS / "evidence-export.json").write_text(json.dumps(
        {k: ev[k] for k in ("budget", "acceptance", "routes", "tasks", "latency")}, default=str, indent=1),
        encoding="utf-8")
    print(DOCS / "report.html")


if __name__ == "__main__":
    main()
