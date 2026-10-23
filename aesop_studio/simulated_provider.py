"""Offline adapter simulation used only by tests (route state SIMULATED, never counted live)."""
import sys
import time
from pathlib import Path

mode, out_file = sys.argv[1], sys.argv[2]
prompt = sys.stdin.read()
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
reply = f"[simulated {mode}] received {len(prompt)} chars. token sk-abcdefghijklmnopqrstuvwx"
print(reply, flush=True)
Path(out_file).write_text(reply, encoding="utf-8")
