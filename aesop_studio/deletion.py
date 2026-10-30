"""Owner deletions: conversations and roundtable sessions, including derived copies.

Deleting removes the records and scrubs every derived local copy Studio holds (request prompts, task output
logs, events). It cannot delete anything a provider retained on its side, and existing backup archives keep
their snapshot until they are deleted; both facts are returned so the UI can say so.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from . import plan, team
from .security import ScopeError, contained_path, redact
from .store import Store

NOTE = (
    "Deleted from Studio, including request prompts and output logs. Copies already sent to providers and "
    "older backup archives are not affected."
)


def _scrub_tasks(store: Store, task_ids: set[str]) -> int:
    n = 0
    for tid in task_ids:
        t = store.one("SELECT output_path FROM tasks WHERE id=?", (tid,))
        if not t:
            continue
        for suffix in ("", ".last.txt", ".before.json", ".err"):
            try:
                if t["output_path"]:
                    os.remove(t["output_path"] + suffix)
            except OSError:
                pass
        store.x(
            "UPDATE tasks SET prompt='[deleted by owner]', checkpoint=json_set(COALESCE(checkpoint,'{}'),"
            "'$.result','[deleted by owner]') WHERE id=?",
            (tid,),
        )
        n += 1
    return n


def _expand_team_tasks(store: Store, seeds: set[str]) -> set[str]:
    """Follow team records from message task ids (cycle-safe)."""
    out: set[str] = set()
    stack = list(seeds)
    expanded: set[str] = set()
    while stack:
        tid = stack.pop()
        if tid in out:
            continue
        out.add(tid)
        if tid in expanded:
            continue
        expanded.add(tid)
        rec = team.get(store, tid)
        if not rec:
            continue
        for key in ("review_task", "fix_task"):
            nxt = rec.get(key)
            if nxt:
                stack.append(nxt)
    return out


def _delete_team_records(store: Store, task_ids: set[str]) -> None:
    for tid in task_ids:
        store.x("DELETE FROM kv WHERE k=?", (f"team:{tid}",))


def _composer_prompt_for_build_plan(store: Store, tid: str) -> str | None:
    """Text passed to plan.add_for_task at creation (message composer or build prompt)."""
    asst = store.one(
        "SELECT conversation_id, created FROM messages WHERE role='assistant' AND meta LIKE ?",
        (f'%"task_id": "{tid}"%',),
    )
    if asst:
        for row in store.q(
            "SELECT content, meta FROM messages WHERE conversation_id=? AND role='user' "
            "AND created <= ? ORDER BY created DESC",
            (asst["conversation_id"], asst["created"]),
        ):
            meta = json.loads(row["meta"] or "{}")
            if meta.get("work"):
                return row["content"]
    for row in store.q("SELECT role, content, meta FROM messages ORDER BY created"):
        meta = json.loads(row["meta"] or "{}")
        if meta.get("task_id") == tid and row["role"] == "user":
            return row["content"]
    task = store.one("SELECT prompt FROM tasks WHERE id=?", (tid,))
    if task:
        return task["prompt"]
    return None


def _delete_build_plan_items(store: Store, task_ids: set[str]) -> int:
    if not task_ids:
        return 0
    plan.ensure_schema(store)
    ph = ",".join("?" * len(task_ids))
    rows = store.q(
        f"SELECT id, content, task_ref FROM plan_items WHERE source='build' AND task_ref IN ({ph})",
        tuple(task_ids),
    )
    removed = 0
    for row in rows:
        tid = row["task_ref"]
        composer = _composer_prompt_for_build_plan(store, tid)
        if composer is None:
            continue
        expected = plan.auto_build_label(composer)
        if row["content"] != expected:
            continue
        with store.tx() as c:
            n = c.execute(
                "DELETE FROM plan_items WHERE id=? AND content=? AND task_ref=?",
                (row["id"], row["content"], tid),
            ).rowcount
        removed += n
    return removed


def _remove_staged_photo_dirs(store: Store, task_ids: set[str]) -> int:
    """Remove .aesop/photos/<task id>/ under each task cwd (never follow directory symlinks)."""
    removed = 0
    for tid in task_ids:
        row = store.one("SELECT cwd FROM tasks WHERE id=?", (tid,))
        if not row or not row["cwd"]:
            continue
        cwd_path = Path(row["cwd"])
        if not cwd_path.exists():
            continue
        try:
            cwd = cwd_path.resolve()
        except OSError:
            continue
        rel = f".aesop/photos/{tid}"
        try:
            dest = contained_path(cwd, rel)
        except ScopeError:
            continue
        expected = (cwd / ".aesop" / "photos" / tid).resolve()
        if dest != expected:
            continue
        if dest.is_symlink():
            dest.unlink(missing_ok=True)
            removed += 1
            continue
        if dest.is_dir():
            shutil.rmtree(dest)
            removed += 1
    return removed


def delete_conversation(store: Store, svc, pid: str, cid: str) -> dict:
    svc.project(pid)
    if not store.one(
        "SELECT id FROM conversations WHERE id=? AND project_id=?", (cid, pid)
    ):
        raise KeyError("conversation not in this project")
    tids, used = set(), set()
    for m in store.q("SELECT meta FROM messages WHERE conversation_id=?", (cid,)):
        meta = json.loads(m["meta"] or "{}")
        if meta.get("task_id"):
            tids.add(meta["task_id"])
        used.update(meta.get("attachments") or [])
    scrub_ids = _expand_team_tasks(store, tids)
    plan_removed = _delete_build_plan_items(store, scrub_ids)
    scrubbed = _scrub_tasks(store, scrub_ids)
    _delete_team_records(store, scrub_ids)
    staged_photos = _remove_staged_photo_dirs(store, scrub_ids)
    with store.tx() as c:
        n = c.execute("DELETE FROM messages WHERE conversation_id=?", (cid,)).rowcount
        c.execute("DELETE FROM conversations WHERE id=?", (cid,))
    photos = _drop_unused_photos(store, pid, used)
    store.event(
        "conversation_deleted",
        pid,
        conversation_id=cid,
        messages=n,
        photos=photos,
        staged_photos=staged_photos,
        plan_items=plan_removed,
        at=time.time(),
    )
    return {
        "deleted": cid,
        "messages": n,
        "photos_deleted": photos,
        "requests_scrubbed": scrubbed,
        "note": NOTE,
    }


def _drop_unused_photos(store: Store, pid: str, ids: set) -> int:
    """Photos sent in a deleted conversation go with it, unless another message still shows them."""
    gone = 0
    for aid in ids:
        a = store.one(
            "SELECT stored_path, sha256 FROM attachments WHERE id=? AND project_id=? AND extract_status='image'",
            (aid, pid),
        )
        if not a or store.one(
            "SELECT id FROM messages WHERE meta LIKE ?", (f'%"{aid}"%',)
        ):
            continue
        store.x("DELETE FROM attachments WHERE id=?", (aid,))
        if a["stored_path"] and not store.one(
            "SELECT id FROM attachments WHERE stored_path=?", (a["stored_path"],)
        ):
            try:
                (store.data_dir / a["stored_path"]).unlink()
            except OSError:
                pass
        gone += 1
    return gone


def delete_roundtable(store: Store, rid: str) -> dict:
    r = store.one("SELECT project_id FROM roundtables WHERE id=?", (rid,))
    if not r:
        raise KeyError("roundtable not found")
    tids = {
        e["task_id"]
        for e in store.q(
            "SELECT task_id FROM roundtable_events WHERE rt_id=? AND task_id IS NOT NULL",
            (rid,),
        )
    }
    from . import followup

    tids |= followup.forget(store, rid)
    scrubbed = _scrub_tasks(store, tids)
    with store.tx() as c:
        n = c.execute("DELETE FROM roundtable_events WHERE rt_id=?", (rid,)).rowcount
        c.execute("DELETE FROM roundtables WHERE id=?", (rid,))
    store.event(
        "roundtable_deleted",
        r["project_id"],
        roundtable_id=rid,
        events=n,
        at=time.time(),
    )
    return {"deleted": rid, "events": n, "requests_scrubbed": scrubbed, "note": NOTE}
