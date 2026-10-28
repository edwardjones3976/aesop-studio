"""Investigator check: does the cached `routes` kv blob agree with the per-route `verify:<rid>` records?

Usage: python tools/cache_vs_source.py [data_dir] [--fix]
Lists every route whose cached state, evidence or last_verified_at differs from its verify record. `--fix` calls
providers.refresh() so the blob is rebuilt from the records. Exit 0 = consistent, 1 = drift found, 2 = error.
Background: 2026-10-26 the panel showed UNVERIFIED for cursor/grok/zai/perplexity while the verify records were
ok, because verify_live() wrote the record but never refreshed the blob (fixed in PR #4). This catches a regression.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aesop_studio import providers
from aesop_studio.store import Store


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    data_dir = args[0] if args else os.environ.get("AESOP_DATA_DIR") or str(Path.home() / ".aesop-studio")
    if not Path(data_dir).is_dir():
        print(f"no data dir at {data_dir}")
        return 2
    store = Store(data_dir)
    row = store.one("SELECT v FROM kv WHERE k='routes'")
    blob = json.loads(row["v"]) if row else {}
    drift = []
    for rid in sorted(blob):
        rec_row = store.one("SELECT v FROM kv WHERE k=?", (f"verify:{rid}",))
        if not rec_row:
            continue
        rec = json.loads(rec_row["v"])
        cached = blob[rid]
        for key in ("state", "evidence", "last_verified_at"):
            if key in rec and rec.get(key) != cached.get(key):
                drift.append((rid, key, cached.get(key), rec.get(key)))
    for rid, key, c, r in drift:
        print(f"DRIFT {rid:<24} {key:<17} blob={str(c)[:50]!r}  record={str(r)[:50]!r}")
    if not drift:
        print(f"consistent: {len(blob)} routes, blob matches verify records")
        return 0
    if "--fix" in sys.argv:
        providers.refresh(store)
        print("refreshed routes blob from live probe")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
