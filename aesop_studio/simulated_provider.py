"""Offline adapter simulation used only by tests (route state SIMULATED, never counted live)."""

import os
import sys
import time
from pathlib import Path

mode, out_file = sys.argv[1], sys.argv[2]
if (
    os.environ.get("AESOP_SIM_NOREAD") == "1"
):  # fixture: never read stdin, just hang (stdin-deadlock test)
    time.sleep(60)
    sys.exit(0)
prompt = sys.stdin.read()
rendezvous_dir = os.environ.get("AESOP_SIM_RENDEZVOUS_DIR")
if rendezvous_dir and "independent OPENING position" in prompt:
    r_dir = Path(rendezvous_dir)
    r_dir.mkdir(parents=True, exist_ok=True)
    if not (r_dir / "rendezvous_met").exists() and not (r_dir / "failure.txt").exists():
        expected = int(os.environ.get("AESOP_SIM_RENDEZVOUS_COUNT", "4"))
        timeout = float(os.environ.get("AESOP_SIM_RENDEZVOUS_TIMEOUT", "10.0"))
        inflight_file = r_dir / f"inflight_{os.getpid()}_{time.time_ns()}"
        inflight_file.write_text("1", encoding="utf-8")
        try:
            deadline = time.time() + timeout
            while True:
                if (r_dir / "rendezvous_met").exists():
                    break
                if (r_dir / "failure.txt").exists():
                    break
                if len(list(r_dir.glob("inflight_*"))) >= expected:
                    (r_dir / "rendezvous_met").write_text("ok", encoding="utf-8")
                    time.sleep(0.05)
                    break
                if time.time() >= deadline:
                    if not (r_dir / "rendezvous_met").exists() and not (r_dir / "failure.txt").exists():
                        saw = len(list(r_dir.glob("inflight_*")))
                        (r_dir / "failure.txt").write_text(
                            f"Rendezvous failed: opening turns were not concurrent; "
                            f"timed out after {timeout}s waiting for {expected} opening turns "
                            f"to be in flight simultaneously (saw {saw})",
                            encoding="utf-8",
                        )
                    break
                time.sleep(0.02)
        finally:
            try:
                inflight_file.unlink(missing_ok=True)
            except OSError:
                pass

if "BIGOUT" in prompt:  # fixture: 3 MB of output with no newline (bounded-reader test)
    sys.stdout.write("x" * (3 * 1024 * 1024))
    sys.stdout.flush()
if "SLEEP" in prompt:
    for i in range(600):
        print(f"working {i}", flush=True)
        time.sleep(0.1)
if "ORPHAN" in prompt:
    import subprocess

    gc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdout=sys.stdout,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    print(f"grandchild {gc.pid} holds stdout", flush=True)
if mode == "agent" and "WRITE" in prompt:
    Path("sim_output.txt").write_text("written by simulated agent\n", encoding="utf-8")
if (
    "FLAKY" in prompt
):  # fixture: first call fails with a transient 503, the next succeeds (retry test)
    marker = Path(os.environ.get("AESOP_SIM_FLAKY_FILE", "flaky.marker"))
    if not marker.exists():
        marker.write_text("1", encoding="utf-8")
        print("API Error: 503 service unavailable", flush=True)
        sys.exit(1)
if "FAIL" in prompt:
    print("simulated failure", file=sys.stderr)
    sys.exit(3)
import json as _json
import re as _re

reply = f"[simulated {mode}] received {len(prompt)} chars. token sk-abcdefghijklmnopqrstuvwx"
staged = Path(".aesop") / "photos"
if staged.is_dir():
    n = sum(1 for p in staged.rglob("*") if p.is_file())
    if n:
        reply += f" photos={n}"
elif Path("images").is_dir():
    reply += f" photos={len(list(Path('images').iterdir()))}"
if (
    "Return ONLY a JSON array" in prompt
):  # draft-findings fixture: cite the first source, plus one bad citation
    sid = (_re.findall(r'<source id="([^"]+)"', prompt) or ["none"])[0]
    reply = _json.dumps(
        [
            {
                "claim": "Synthetic widgets improved 3%",
                "source_id": sid,
                "locator": "line 1",
                "limitation": "single synthetic study",
            },
            {
                "claim": "Invented claim",
                "source_id": "src_elsewhere",
                "locator": "",
                "limitation": "",
            },
        ]
    )
elif 'Return ONLY JSON: {"summary"' in prompt:  # summarize fixture
    mids = _re.findall(r'<message id="([^"]+)"', prompt)
    reply = _json.dumps(
        {
            "summary": "The team chose SQLite for notes.",
            "source_ids": mids[:1] + ["msg_bogus"],
            "open_questions": ["Backup cadence?"],
        }
    )
if (
    "REFERENCE STUDY" in prompt
):  # reference-study fixture: a short report, then the fenced JSON contract
    reply = (
        "## Observed behavior\nThe composer keeps drafts per conversation.\n\n## Evidence\n"
        "renderer/composer.js registers an IPC channel 'draft:save'.\n\n## Limitations\nMinified bundle.\n\n"
        "```json\n"
        + _json.dumps(
            {
                "findings": [
                    {
                        "claim": "Drafts are saved per conversation on every keystroke",
                        "evidence": "renderer/composer.js -> ipc draft:save",
                        "limitation": "bundle is minified",
                    },
                    {
                        "claim": "Attachments are previewed before send",
                        "evidence": "renderer/attach.js",
                        "limitation": "",
                    },
                ],
                "steps": [
                    "Keep an unsent draft per conversation in localStorage",
                    "Show attachment previews before send",
                ],
            }
        )
        + "\n```"
    )
if "JSON array of plan items" in prompt:  # plan-draft fixture
    reply = _json.dumps(
        [{"step": "Wire the scoring table"}, {"step": "Add renege detection"}]
    )
if (
    os.environ.get("AESOP_SIM_ASK_RESEARCH") == "1"
    and "Researcher on call" in prompt
    and "OPENING" in prompt
):
    reply += "\nRESEARCH: sqlite vs lmdb durability for note storage"
print(reply, flush=True)
Path(out_file).write_text(reply, encoding="utf-8")
