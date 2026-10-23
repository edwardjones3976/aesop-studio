"""Local backup (SQLite online-backup snapshot + stored files + manifest) and verified restore."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path

from .store import Store


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def create_backup(store: Store, dest_dir: str | Path) -> Path:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = dest_dir / f"aesop-backup-{stamp}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "aesop.db"
        src = sqlite3.connect(store.path)
        dst = sqlite3.connect(snap)
        with dst:
            src.backup(dst)  # consistent snapshot even while the app is writing
        src.close()
        dst.close()
        entries = {"aesop.db": _sha(snap)}
        files_root = store.data_dir / "files"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(snap, "aesop.db")
            for f in sorted(files_root.rglob("*")):
                if f.is_file() and not f.is_symlink():
                    arc = "files/" + f.relative_to(files_root).as_posix()
                    z.write(f, arc)
                    entries[arc] = _sha(f)
            con = sqlite3.connect(snap)
            counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                      for t in ("projects", "conversations", "messages", "attachments", "artifacts", "tasks",
                                "sources", "findings", "memory", "ledger")}
            con.close()
            manifest = {"format": "aesop-backup/1", "created": time.time(), "entries": entries, "counts": counts,
                        "credentials": "excluded: provider sign-ins live in each official CLI; re-run "
                                       "`codex login` / `claude auth login` after restoring on a new machine"}
            z.writestr("manifest.json", json.dumps(manifest, indent=2))
    return out


def restore_backup(archive: str | Path, target_dir: str | Path, live_data_dir: str | Path | None = None) -> dict:
    """Restore into a separate empty directory and verify integrity. Never restores over live records."""
    target = Path(target_dir).resolve()
    if live_data_dir and target == Path(live_data_dir).resolve():
        raise ValueError("refusing to restore over the live data directory")
    if target.exists() and any(target.iterdir()):
        raise ValueError("restore target must be empty")
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read("manifest.json"))
        for name in manifest["entries"]:
            dest = (target / name).resolve()
            if "\\" in name or ":" in name or name.startswith("/") or target not in dest.parents:
                raise ValueError(f"unsafe entry {name}")
        for name in manifest["entries"]:
            dest = target / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(name))
    mismatches = [n for n, h in manifest["entries"].items() if _sha(target / n) != h]
    con = sqlite3.connect(target / "aesop.db")
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in manifest["counts"]}
    con.close()
    ok = not mismatches and integrity == "ok" and counts == manifest["counts"]
    return {"ok": ok, "target": str(target), "hash_mismatches": mismatches, "integrity": integrity,
            "counts": counts, "expected_counts": manifest["counts"], "reauth": manifest["credentials"]}
