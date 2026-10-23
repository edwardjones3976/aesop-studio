"""Owner deletions: conversations and roundtable sessions, including derived copies.

Deleting removes the records and scrubs every derived local copy Studio holds (request prompts, task output
logs, events). It cannot delete anything a provider retained on its side, and existing backup archives keep
their snapshot until they are deleted; both facts are returned so the UI can say so.
"""
from __future__ import annotations

import json
import os
import time

from .store import Store

NOTE = ("Deleted from Studio, including request prompts and output logs. Copies already sent to providers and "
        "older backup archives are not affected.")


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
        store.x("UPDATE tasks SET prompt='[deleted by owner]', checkpoint=json_set(COALESCE(checkpoint,'{}'),"
                "'$.result','[deleted by owner]') WHERE id=?", (tid,))
        n += 1
    return n


def delete_conversation(store: Store, svc, pid: str, cid: str) -> dict:
    svc.project(pid)
    if not store.one("SELECT id FROM conversations WHERE id=? AND project_id=?", (cid, pid)):
        raise KeyError("conversation not in this project")
    tids, used = set(), set()
    for m in store.q("SELECT meta FROM messages WHERE conversation_id=?", (cid,)):
        meta = json.loads(m["meta"] or "{}")
        if meta.get("task_id"):
            tids.add(meta["task_id"])
        used.update(meta.get("attachments") or [])
    scrubbed = _scrub_tasks(store, tids)
    with store.tx() as c:
        n = c.execute("DELETE FROM messages WHERE conversation_id=?", (cid,)).rowcount
        c.execute("DELETE FROM conversations WHERE id=?", (cid,))
    photos = _drop_unused_photos(store, pid, used)
    store.event("conversation_deleted", pid, conversation_id=cid, messages=n, photos=photos, at=time.time())
    return {"deleted": cid, "messages": n, "photos_deleted": photos, "requests_scrubbed": scrubbed, "note": NOTE}


def _drop_unused_photos(store: Store, pid: str, ids: set) -> int:
    """Photos sent in a deleted conversation go with it, unless another message still shows them."""
    gone = 0
    for aid in ids:
        a = store.one("SELECT stored_path, sha256 FROM attachments WHERE id=? AND project_id=? AND extract_status='image'",
                      (aid, pid))
        if not a or store.one("SELECT id FROM messages WHERE meta LIKE ?", (f'%"{aid}"%',)):
            continue
        store.x("DELETE FROM attachments WHERE id=?", (aid,))
        if a["stored_path"] and not store.one("SELECT id FROM attachments WHERE stored_path=?", (a["stored_path"],)):
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
    tids = {e["task_id"] for e in store.q("SELECT task_id FROM roundtable_events WHERE rt_id=? AND task_id IS NOT NULL",
                                          (rid,))}
    from . import followup
    tids |= followup.forget(store, rid)
    scrubbed = _scrub_tasks(store, tids)
    with store.tx() as c:
        n = c.execute("DELETE FROM roundtable_events WHERE rt_id=?", (rid,)).rowcount
        c.execute("DELETE FROM roundtables WHERE id=?", (rid,))
    store.event("roundtable_deleted", r["project_id"], roundtable_id=rid, events=n, at=time.time())
    return {"deleted": rid, "events": n, "requests_scrubbed": scrubbed, "note": NOTE}
