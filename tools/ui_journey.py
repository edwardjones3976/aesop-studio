"""Real end-to-end UI journey against the owner's running Studio (live providers, not simulated).

project -> approved provider (codex, official CLI) -> attached synthetic file -> response -> saved
artifact; then the metered OpenAI route under the mission permit (streamed, costed); then a server
restart and resume check. Screenshots go to docs/qa/journey/. Uses only synthetic content.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("LOCALAPPDATA", ".")) / "AesopStudio"
OUT = ROOT / "docs" / "qa" / "journey"
PROJ = ROOT / ".sandbox" / "journey"
BRIEF = ROOT / ".sandbox" / "journey-brief.md"


def restart() -> str:
    quiet = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # server inherits handles
    subprocess.run(["pwsh", "-NoProfile", "-File", str(ROOT / "stop.ps1")], **quiet)
    time.sleep(1)
    subprocess.run(["pwsh", "-NoProfile", "-File", str(ROOT / "start.ps1"), "-NoBrowser"], check=True, **quiet)
    return (DATA / "launch-link.txt").read_text(encoding="utf-8").strip()


def wait_generated(page, count: int, timeout_s: int) -> float:
    """Wait until the conversation holds `count` generated assistant messages (by API state, not page text)."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        n = page.evaluate("""async () => { const pid = S.project.id, cid = S.conv;
            const r = await fetch(`/api/projects/${pid}/conversations/${cid}/messages`,
                {headers: {'X-Aesop-Key': sessionStorage.getItem('aesop.key') || ''}}); const m = await r.json();
            return m.filter(x => x.role === 'assistant' && x.status === 'generated').length; }""")
        if n >= count:
            return time.time() - t0
        page.wait_for_timeout(250)
    raise TimeoutError(f"{count} generated messages")


def wait_text(page, pattern: str, timeout_s: int) -> float:
    t0 = time.time()
    rx = re.compile(pattern, re.I)
    while time.time() - t0 < timeout_s:
        if rx.search(page.locator("#view").inner_text()):
            return time.time() - t0
        page.wait_for_timeout(250)
    raise TimeoutError(pattern)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    PROJ.mkdir(parents=True, exist_ok=True)
    BRIEF.write_text("# Synthetic brief\nThe demo project ships a tiny CLI named ripple. Deadline: Friday.\n",
                     encoding="utf-8")
    log: dict = {"steps": []}
    step = lambda name, **kw: log["steps"].append({"step": name, **kw}) or print(name, kw)
    link = restart()
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="chrome", headless=True)
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(link)
        page.wait_for_timeout(1200)

        # 1. Create project through the UI dialog
        page.click("#newProjectBtn")
        page.fill("#dlgForm [name=name]", "Live journey (QA, synthetic)")
        page.fill("#dlgForm [name=root]", str(PROJ))
        page.select_option("#dlgForm [name=provider_default]", "codex")
        page.click("#dlgForm button[value=ok]")
        page.wait_for_timeout(1200)
        step("project_created", title=page.locator("#projTitle").inner_text())

        # 2. Allow sending attached files to codex (Settings dialog)
        page.click("#settingsBtn")
        page.select_option("#dlgForm [name=tp_codex]", "yes")
        page.click("#dlgForm button[value=ok]")
        page.wait_for_timeout(800)

        # 3. Attach the synthetic file through the inspector Files tab
        page.evaluate("() => [...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Files')?.click()")
        page.wait_for_timeout(500)
        page.set_input_files("input[type=file]", str(BRIEF))
        page.wait_for_timeout(1500)
        step("file_attached")

        # 4. Chat via official CLI route
        page.evaluate("() => document.querySelector('[data-tab=chat]').click()")
        page.wait_for_timeout(800)
        start = page.locator("button", has_text="Start a conversation")
        if start.count():
            start.first.click()
            page.wait_for_timeout(800)
        page.locator(".achip", has_text="journey-brief.md").first.click()
        page.fill("textarea[aria-label=Message]", "What is the CLI called and when is the deadline? One sentence.")
        t0 = time.time()
        page.keyboard.press("Control+Enter")
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT / "1-codex-pending.png"))
        wait_generated(page, 1, 240)
        step("codex_answer", end_to_end_s=round(time.time() - t0, 2))
        page.screenshot(path=str(OUT / "2-codex-answer.png"))
        page.locator("button.linkish", has_text="Save").last.click()
        page.wait_for_timeout(800)
        step("artifact_saved")

        # 5. Paid OpenAI route under the mission permit (enabled from the UI, disabled after)
        page.evaluate("() => document.querySelector('[data-global=evidence]').click()")
        page.wait_for_timeout(1200)
        page.click("button[role=switch]")
        page.wait_for_timeout(1200)
        step("permit_on", aria=page.get_attribute("button[role=switch]", "aria-checked"))
        page.evaluate("() => document.querySelector('[data-tab=chat]').click()")
        page.wait_for_timeout(800)
        page.select_option("#providerSel", "openai-api")
        page.wait_for_timeout(1000)
        page.click("#settingsBtn")
        page.select_option("#dlgForm [name='tp_openai-api']", "yes")
        page.click("#dlgForm button[value=ok]")
        page.wait_for_timeout(800)
        page.locator(".achip", has_text="journey-brief.md").first.click()
        page.fill("textarea[aria-label=Message]", "Same question. Answer in under 12 words.")
        t0 = time.time()
        page.keyboard.press("Control+Enter")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT / "3-api-streaming.png"))
        wait_generated(page, 2, 120)
        page.wait_for_timeout(1500)
        step("api_answer_with_cost", end_to_end_s=round(time.time() - t0, 2))
        page.screenshot(path=str(OUT / "4-api-answer-cost.png"))
        page.evaluate("() => document.querySelector('[data-global=evidence]').click()")
        page.wait_for_timeout(1200)
        if page.get_attribute("button[role=switch]", "aria-checked") == "true":
            page.click("button[role=switch]")
            page.wait_for_timeout(1000)
        page.screenshot(path=str(OUT / "5-evidence-after.png"), full_page=True)
        step("permit_off", aria=page.get_attribute("button[role=switch]", "aria-checked"))
        b.close()

    # 6. Restart and resume
    link = restart()
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="chrome", headless=True)
        page = b.new_context(viewport={"width": 1440, "height": 900}).new_page()
        page.goto(link)
        page.wait_for_timeout(1500)
        page.locator("#projectList button", has_text="Live journey").first.click()
        page.wait_for_timeout(1000)
        page.evaluate("() => document.querySelector('[data-tab=chat]').click()")
        page.wait_for_timeout(1500)
        txt = page.locator("#view").inner_text()
        page.screenshot(path=str(OUT / "6-resumed-after-restart.png"))
        page.evaluate("() => document.querySelector('[data-tab=artifacts]').click()")
        page.wait_for_timeout(1000)
        saved = page.locator("#view").inner_text()
        step("resumed", has_codex_answer=bool(re.search("ripple", txt, re.I)), has_cost=bool(re.search(r"\$0\.0", txt)),
             artifact_present="ripple" in saved.lower())
        b.close()
    log["page_errors"] = errs
    (OUT / "journey.json").write_text(json.dumps(log, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
