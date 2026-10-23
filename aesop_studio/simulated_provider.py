"""Offline adapter simulation used only by tests (route state SIMULATED, never counted live)."""
import os
import sys
import time
from pathlib import Path

mode, out_file = sys.argv[1], sys.argv[2]
if os.environ.get("AESOP_SIM_NOREAD") == "1":  # fixture: never read stdin, just hang (stdin-deadlock test)
    time.sleep(60)
    sys.exit(0)
prompt = sys.stdin.read()
if "BIGOUT" in prompt:  # fixture: 3 MB of output with no newline (bounded-reader test)
    sys.stdout.write("x" * (3 * 1024 * 1024))
    sys.stdout.flush()
if "SLEEP" in prompt:
    for i in range(600):
        print(f"working {i}", flush=True)
        time.sleep(0.1)
if "ORPHAN" in prompt:
    import subprocess
    gc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], stdout=sys.stdout,
                     creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    print(f"grandchild {gc.pid} holds stdout", flush=True)
if mode == "agent" and "WRITE" in prompt:
    Path("sim_output.txt").write_text("written by simulated agent\n", encoding="utf-8")
if "FAIL" in prompt:
    print("simulated failure", file=sys.stderr)
    sys.exit(3)
import json as _json
import re as _re
reply = f"[simulated {mode}] received {len(prompt)} chars. token sk-abcdefghijklmnopqrstuvwx"
if "Return ONLY a JSON array" in prompt:  # draft-findings fixture: cite the first source, plus one bad citation
    sid = (_re.findall(r'<source id="([^"]+)"', prompt) or ["none"])[0]
    reply = _json.dumps([{"claim": "Synthetic widgets improved 3%", "source_id": sid, "locator": "line 1",
                          "limitation": "single synthetic study"},
                         {"claim": "Invented claim", "source_id": "src_elsewhere", "locator": "", "limitation": ""}])
elif "Return ONLY JSON: {\"summary\"" in prompt:  # summarize fixture
    mids = _re.findall(r'<message id="([^"]+)"', prompt)
    reply = _json.dumps({"summary": "The team chose SQLite for notes.", "source_ids": mids[:1] + ["msg_bogus"],
                         "open_questions": ["Backup cadence?"]})
print(reply, flush=True)
Path(out_file).write_text(reply, encoding="utf-8")
