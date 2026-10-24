"""Run a project's own tests after a build, outside the AI sandboxes (owner request 2026-10-23).

The builders and reviewers often cannot start Python inside their sandboxes, so Studio runs the tests itself, on
this PC as the owner's Windows user: the project's test command only, in the project folder, with a time limit,
the whole process tree killed on timeout, and an environment with every key/token/secret variable removed.
Detection is conservative and explained in the result; nothing runs when no tests are found.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from .security import redact

TIMEOUT_S = 180
OUTPUT_TAIL = 8000
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build", ".tox"}
_SECRETISH = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|COOKIE|SESSION)", re.I)
NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _python(root: Path) -> str | None:
    root = root.resolve()
    for cand in (root / ".venv" / "Scripts" / "python.exe", root / "venv" / "Scripts" / "python.exe",
                 root / ".venv" / "bin" / "python", root / "venv" / "bin" / "python"):
        if cand.is_file():
            return str(cand)
    return shutil.which("python") or shutil.which("py")


def _has_py_tests(root: Path) -> bool:
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            n += 1
            if f.endswith(".py") and (f.startswith("test_") or f.endswith("_test.py")):
                return True
            if n > 4000:
                return False
    return False


def detect(root: str) -> dict | None:
    """The command Studio would run, with why; None when the project has no recognisable tests."""
    r = Path(root)
    pkg = r / "package.json"
    if pkg.is_file():
        try:
            script = (json.loads(pkg.read_text(encoding="utf-8")).get("scripts") or {}).get("test") or ""
        except (OSError, ValueError):
            script = ""
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if script and "no test specified" not in script and npm:
            return {"argv": [npm, "test", "--silent"], "label": "npm test", "why": "package.json has a test script"}
    if _has_py_tests(r):
        py = _python(r)
        if not py:
            return {"argv": None, "label": "python tests", "why": "test files found but no Python interpreter on PATH"}
        uses_pytest = any((r / f).is_file() for f in ("pytest.ini", "conftest.py")) or \
            "pytest" in ((r / "pyproject.toml").read_text(encoding="utf-8", errors="ignore") if (r / "pyproject.toml").is_file() else "")
        if uses_pytest:
            ok = subprocess.run([py, "-c", "import pytest"], capture_output=True, timeout=30,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).returncode == 0
            if ok:
                return {"argv": [py, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"], "label": "pytest",
                        "why": "pytest configuration found"}
        return {"argv": [py, "-m", "unittest", "discover", "-v", "-p", "test*.py"], "label": "python -m unittest",
                "why": "test_*.py files found"}
    return None


def _summary(label: str, out: str, code: int | None) -> tuple[str, int | None, int | None]:
    """(one line, passed, failed) parsed from common runners; falls back to the exit code."""
    m = re.search(r"Ran (\d+) tests? in [\d.]+s\s*\n+\s*(OK|FAILED)(?: \(([^)]*)\))?", out)
    if m:
        total = int(m.group(1))
        bad = sum(int(x) for x in re.findall(r"(?:failures|errors)=(\d+)", m.group(3) or ""))
        return (f"{total - bad} of {total} passed" if bad else f"all {total} passed"), total - bad, bad
    m = re.search(r"(\d+) passed", out)
    f = re.search(r"(\d+) failed", out)
    e = re.search(r"(\d+) errors?", out)
    if m or f:
        p, bad = int(m.group(1)) if m else 0, (int(f.group(1)) if f else 0) + (int(e.group(1)) if e else 0)
        return (f"{p} passed, {bad} failed" if bad else f"all {p} passed"), p, bad
    if code == 0:
        return "passed (exit code 0)", None, 0
    return f"failed (exit code {code})", None, None


def run(root: str) -> dict:
    cmd = detect(root)
    if not cmd:
        return {"state": "NO_TESTS", "note": "no tests found (looked for test_*.py files and an npm test script)"}
    if not cmd["argv"]:
        return {"state": "ERROR", "label": cmd["label"], "note": cmd["why"]}
    env = {k: v for k, v in os.environ.items() if not _SECRETISH.search(k)}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    t0 = time.time()
    try:
        p = subprocess.Popen(cmd["argv"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             env=env, creationflags=NEW_GROUP)
    except OSError as e:
        return {"state": "ERROR", "label": cmd["label"], "note": f"could not start: {type(e).__name__}"}
    try:
        out, _ = p.communicate(timeout=TIMEOUT_S)
        code = p.returncode
        timed_out = False
    except subprocess.TimeoutExpired:
        from .tasks import kill_tree
        kill_tree(p.pid)
        out, _ = p.communicate()
        code, timed_out = None, True
    text = redact((out or b"").decode("utf-8", "replace"))
    line, passed, failed = _summary(cmd["label"], text, code)
    if timed_out:
        line = f"timed out after {TIMEOUT_S}s"
    return {"state": "PASSED" if code == 0 and not timed_out else "FAILED", "label": cmd["label"], "why": cmd["why"],
            "exit_code": code, "summary": line, "passed": passed, "failed": failed,
            "duration_s": round(time.time() - t0, 1), "output": text[-OUTPUT_TAIL:]}
