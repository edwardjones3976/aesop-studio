"""Local backup (SQLite online-backup snapshot + stored files + task logs + manifest) and verified restore."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

from .security import redact
from .store import Store

TABLES = ("projects", "conversations", "messages", "attachments", "artifacts", "tasks",
          "sources", "findings", "memory", "ledger")


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _unique_name() -> str:
    """Sorts by creation time (second stamp, then nanoseconds) and never repeats (uuid tail)."""
    ns = time.time_ns()
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(ns // 1_000_000_000))
    return f"aesop-backup-{stamp}-{ns % 1_000_000_000:09d}-{uuid.uuid4().hex[:8]}.zip"


def _publish(tmp: Path, out: Path) -> None:
    """Move the finished temp archive to its final name without ever replacing an existing archive."""
    try:
        os.link(tmp, out)  # raises FileExistsError if out exists
    except FileExistsError:
        raise
    except OSError:
        if os.name != "nt":
            raise
        os.rename(tmp, out)  # on Windows rename refuses an existing destination
        return
    os.unlink(tmp)


def create_backup(store: Store, dest_dir: str | Path) -> Path:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(5):
        out = dest_dir / _unique_name()
        tmp = dest_dir / f".{out.name}.partial"  # never matched by the aesop-backup-*.zip glob
        try:
            fh = open(tmp, "xb")  # exclusive create: two backups can never share a file
        except FileExistsError:
            continue
        break
    else:
        raise RuntimeError("could not allocate a unique backup name")
    try:
        with fh, tempfile.TemporaryDirectory() as td:
            snap = Path(td) / "aesop.db"
            src = sqlite3.connect(store.path)
            dst = sqlite3.connect(snap)
            with dst:
                src.backup(dst)  # consistent snapshot even while the app is writing
            src.close()
            dst.close()
            entries = {"aesop.db": _sha(snap)}
            task_outputs = []
            with zipfile.ZipFile(fh, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(snap, "aesop.db")
                files_root = store.data_dir / "files"
                for f in sorted(files_root.rglob("*")):
                    if f.is_file() and not f.is_symlink() and not f.name.endswith(".partial"):
                        arc = "files/" + f.relative_to(files_root).as_posix()
                        z.write(f, arc)
                        entries[arc] = _sha(f)
                out_root = store.data_dir / "task-output"
                for f in (sorted(out_root.iterdir()) if out_root.is_dir() else []):
                    # .before.json is a transient file snapshot; .last.txt is a CLI's raw (unredacted)
                    # answer whose redacted copy already lives in the task checkpoint.
                    if not f.is_file() or f.is_symlink() or f.name.endswith((".before.json", ".last.txt")):
                        continue
                    data = redact(f.read_text(encoding="utf-8", errors="replace")).encode("utf-8")
                    arc = "task-output/" + f.name
                    z.writestr(arc, data)
                    entries[arc] = hashlib.sha256(data).hexdigest()
                    task_outputs.append(arc)
                con = sqlite3.connect(snap)
                counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}
                con.close()
                manifest = {"format": "aesop-backup/1", "created": time.time(), "entries": entries,
                            "counts": counts, "data_dir": str(store.data_dir), "task_outputs": task_outputs,
                            "credentials": "excluded: provider sign-ins live in each official CLI; re-run "
                                           "`codex login` / `claude auth login` after restoring on a new machine",
                            "external": "excluded: project root folders (agent working directories) are the "
                                        "owner's own files and are not part of this backup"}
                z.writestr("manifest.json", json.dumps(manifest, indent=2))
        with zipfile.ZipFile(tmp) as z:
            bad = z.testzip()
        if bad:
            raise RuntimeError(f"backup archive failed self-check at {bad}")
        _publish(tmp, out)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return out


def _remap(path: str, old_root: str | None, target: Path) -> Path | None:
    """Map an absolute path inside the backed-up data dir onto the same place in the restore target."""
    p = path.replace("\\", "/")
    rel = None
    if old_root:
        o = old_root.replace("\\", "/").rstrip("/") + "/"
        if (p.lower().startswith(o.lower()) if os.name == "nt" else p.startswith(o)):
            rel = p[len(o):]
    if rel is None:
        parts = p.split("/")
        if len(parts) >= 2 and parts[-2] == "task-output":  # archives made before data_dir was recorded
            rel = "task-output/" + parts[-1]
    if not rel or any(part in ("", "..") for part in rel.split("/")):
        return None
    return target.joinpath(*rel.split("/"))


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
    mismatches = [n for n, h in manifest["entries"].items() if _sha(target / n) != h]  # before any rewrite
    (target / "files").mkdir(exist_ok=True)
    (target / "task-output").mkdir(exist_ok=True)
    con = sqlite3.connect(target / "aesop.db")
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in manifest["counts"]}
        # tasks.output_path holds absolute paths into the old data dir: point them at the restored copies.
        archived = set(manifest.get("task_outputs", []))
        unmapped, missing, absent_at_backup = [], [], []
        rows = con.execute("SELECT id, output_path FROM tasks WHERE output_path IS NOT NULL AND output_path<>''")
        for tid, path in rows.fetchall():
            new = _remap(path, manifest.get("data_dir"), target)
            if new is None:
                unmapped.append(tid)
                continue
            con.execute("UPDATE tasks SET output_path=? WHERE id=?", (str(new), tid))
            if not new.exists():
                had_log = "task_outputs" not in manifest or f"task-output/{new.name}" in archived
                # a task blocked before it ran never had a log; that is not a backup defect
                (missing if had_log else absent_at_backup).append(tid)
        con.commit()
    finally:
        con.close()
    ok = (not mismatches and integrity == "ok" and counts == manifest["counts"] and not unmapped
          and not missing)
    return {"ok": ok, "target": str(target), "hash_mismatches": mismatches, "integrity": integrity,
            "counts": counts, "expected_counts": manifest["counts"], "reauth": manifest["credentials"],
            "task_outputs_unmapped": unmapped, "task_outputs_missing": missing,
            "task_outputs_absent_at_backup": absent_at_backup,
            "external": manifest.get("external", "project root folders are not part of backups")}
