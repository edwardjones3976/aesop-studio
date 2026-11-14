#!/usr/bin/env python3
"""Fail CI when the diff introduces strings matching aesop_studio/security.py key shapes."""
from __future__ import annotations

import re
import subprocess
import sys

# Keep in sync with aesop_studio/security.py _SECRET_PATTERNS (subset suited to diff scanning).
_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bpplx-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\bfc-(?:live-)?[A-Za-z0-9_\-]{20,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"xox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]

_ALLOWLIST = (
    "[REDACTED]",
    "sk-...",  # README examples
    "sk-ant-...",  # docs
)

# Test fixtures use obviously synthetic key bodies (a run of the alphabet) to prove the redactor strips them.
# No real key is an alphabet sequence, so skipping these keeps real-looking strings in tests still flagged.
_SYNTHETIC = re.compile(r"abcdefghij|ABCDEFGHIJ|0123456789|xxxxxxxxxx")


def _diff_text() -> str:
    base = subprocess.run(
        ["git", "merge-base", "HEAD", "origin/main"],
        capture_output=True,
        text=True,
        check=False,
    )
    if base.returncode == 0 and base.stdout.strip():
        ref = base.stdout.strip()
    else:
        ref = "HEAD~1"
    diff = subprocess.run(
        ["git", "diff", f"{ref}...HEAD", "--unified=0", "--no-color"],
        capture_output=True,
        text=True,
        check=False,
    )
    if diff.returncode != 0 or not diff.stdout.strip():
        diff = subprocess.run(
            ["git", "show", "--format=", "--unified=0", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    return diff.stdout


def main() -> int:
    text = _diff_text()
    added = [ln[1:] for ln in text.splitlines() if ln.startswith("+") and not ln.startswith("+++")]
    body = "\n".join(added)
    hits: list[str] = []
    for pat in _PATTERNS:
        for m in pat.finditer(body):
            frag = m.group(0)
            if any(a in frag for a in _ALLOWLIST) or _SYNTHETIC.search(frag):
                continue
            hits.append(f"{pat.pattern}: …{frag[:24]}…")
    if hits:
        print("Secret scan: possible credential material in diff (+ lines only):", file=sys.stderr)
        for h in hits[:20]:
            print(f"  - {h}", file=sys.stderr)
        return 1
    print("Secret scan: no matching key shapes in diff additions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
