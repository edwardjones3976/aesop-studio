"""Visual/responsive QA for Aesop Studio with Playwright + the installed Chrome.

Starts a throwaway Studio server (temp data dir, loopback, SIMULATED route enabled and labelled as
such), seeds synthetic data through the real API, then screenshots every target viewport and view
and measures page-level horizontal overflow. No provider is called.

Usage: .venv\\Scripts\\python tools\\ui_qa.py --label after [--repo PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

VIEWPORTS = [(1920, 1080), (1440, 900), (1366, 768), (1024, 768), (768, 1024), (390, 844), (360, 780)]
VIEWS = [("chat", "tab"), ("agent", "tab"), ("research", "tab"), ("memory", "tab"),
         ("artifacts", "tab"), ("providers", "global"), ("evidence", "global")]
ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def start_server(repo: Path, data: Path, port: int):
    env = dict(os.environ, AESOP_SIMULATED_ROUTE="1", AESOP_PROBE_OFFLINE="1")
    env.pop("OPENAI_API_KEY", None)
    env["AESOP_OPENAI_KEY_FILE"] = str(data / "no-key")  # QA never sees a real key
    proc = subprocess.Popen([sys.executable if not (repo / ".venv").exists() else "python", "-m", "aesop_studio",
                             "--port", str(port), "--data", str(data)], cwd=repo, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    link = data / "launch-link.txt"
    for _ in range(100):
        if link.exists():
            return proc, link.read_text(encoding="utf-8").strip()
        time.sleep(0.1)
    proc.kill()
    raise RuntimeError("server did not start")


def seed(page, base: str, proj_root: Path) -> None:
    js = """async ([root]) => {
      const K = localStorage.getItem('aesop.key') || '';
      const s = await (await fetch('/api/session', {headers: {'X-Aesop-Key': K}})).json();
      const H = {'Content-Type': 'application/json', 'X-CSRF-Token': s.csrf, 'X-Aesop-Key': K};
      const post = async (u, b) => (await fetch(u, {method: 'POST', headers: H, body: JSON.stringify(b)})).json();
      await post('/api/projects', {name: 'Second project', root});
      const p = await post('/api/projects', {name: 'Ripple CLI', root, provider_default: 'simulated'});
      await fetch('/api/projects/' + p.id, {method: 'PATCH', headers: H, body: JSON.stringify({transfer_policy: {simulated: true}})});
      await fetch('/api/projects/' + p.id + '/attachments', {method: 'POST', headers: {'X-CSRF-Token': s.csrf, 'X-Aesop-Key': K, 'X-Filename': 'brief.md'},
        body: '# Synthetic brief\\nThe demo project ships a tiny CLI named ripple. Deadline: Friday.'});
      const c = await post('/api/projects/' + p.id + '/conversations', {});
      await post('/api/projects/' + p.id + '/conversations/' + c.id + '/messages', {text: 'What is the CLI called?', attachment_ids: []});
      await post('/api/projects/' + p.id + '/agent-ack', {ack: true});
      await post('/api/projects/' + p.id + '/tasks', {prompt: 'WRITE a file (simulated task)'});
      await post('/api/projects/' + p.id + '/notebook/findings', {claim: 'Synthetic finding without a source', locator: ''});
      await post('/api/projects/' + p.id + '/memory', {layer: 'authoritative', kind: 'note', content: 'Owner prefers short answers.'});
      await post('/api/projects/' + p.id + '/artifacts', {kind: 'note', title: 'Saved note', content: 'Synthetic saved output.'});
      return p.id;
    }"""
    return page.evaluate(js, [str(proj_root)])


def open_view(page, name: str, kind: str) -> None:
    sel = f'[data-{"tab" if kind == "tab" else "global"}="{name}"]'
    page.evaluate("(s) => { const el = document.querySelector(s); if (el) el.click(); }", sel)
    page.wait_for_timeout(700)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--views", default=",".join(v for v, _ in VIEWS))
    a = ap.parse_args()
    repo = Path(a.repo).resolve()
    out = ROOT / "docs" / "qa" / a.label
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="aesop-qa-"))
    proj = tmp / "proj"
    proj.mkdir()
    port = free_port()
    proc, link = start_server(repo, tmp / "data", port)
    results = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True)
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: m.type == "error" and errors.append(m.text))
            page.goto(link)
            seed(page, f"http://127.0.0.1:{port}", proj)
            page.wait_for_timeout(1500)
            page.goto(f"http://127.0.0.1:{port}/")
            page.wait_for_timeout(1200)
            wanted = [v for v in VIEWS if v[0] in a.views.split(",")]
            for w, h in VIEWPORTS:
                page.set_viewport_size({"width": w, "height": h})
                page.wait_for_timeout(300)
                for name, kind in wanted:
                    open_view(page, name, kind)
                    m = page.evaluate("""() => ({sw: document.documentElement.scrollWidth,
                        cw: document.documentElement.clientWidth})""")
                    shot = out / f"{w}x{h}-{name}.png"
                    page.screenshot(path=str(shot))
                    results.append({"viewport": f"{w}x{h}", "view": name, "scrollWidth": m["sw"],
                                    "clientWidth": m["cw"], "overflow": m["sw"] > m["cw"] + 1,
                                    "screenshot": str(shot.relative_to(ROOT))})
            results.append({"page_errors": errors})
            browser.close()
    finally:
        proc.kill()
    (out / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    bad = [r for r in results if r.get("overflow")]
    print(f"{len(results) - 1} screenshots -> {out}; overflow: {len(bad)}; page errors: {len(results[-1]['page_errors'])}")
    for r in bad:
        print("  OVERFLOW", r["viewport"], r["view"], r["scrollWidth"], ">", r["clientWidth"])
    for e in results[-1]["page_errors"][:10]:
        print("  ERROR", e[:200])


if __name__ == "__main__":
    main()
