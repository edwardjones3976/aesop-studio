"""Owner deletions: conversations and roundtable sessions, including derived copies."""

import json
import os
import shutil
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path

os.environ["AESOP_SIMULATED_ROUTE"] = "1"
os.environ["AESOP_PROBE_OFFLINE"] = "1"

from aesop_studio import deletion, providers, roundtable  # noqa: E402
from aesop_studio.roundtable_live import ensure_schema  # noqa: E402
from aesop_studio.services import Services  # noqa: E402
from aesop_studio.store import Store  # noqa: E402
from aesop_studio.tasks import TERMINAL, Supervisor  # noqa: E402


class TestDeletion(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aesop-del-"))
        (self.tmp / "p").mkdir()
        self.store = Store(self.tmp / "d")
        self.sup = Supervisor(self.store)
        self.svc = Services(self.store, self.sup)
        providers.refresh(self.store)
        self.p = self.svc.create_project("P", str(self.tmp / "p"), "simulated")

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_delete_conversation_scrubs_requests(self):
        c = self.svc.new_conversation(self.p["id"])
        r = self.svc.send(
            self.p["id"], c["id"], "private question about widgets", [], None
        )
        end = time.time() + 20
        while self.sup.get(r["task_id"])["state"] not in TERMINAL and time.time() < end:
            time.sleep(0.1)
        out = deletion.delete_conversation(self.store, self.svc, self.p["id"], c["id"])
        self.assertEqual(out["messages"], 2)
        self.assertFalse(
            self.store.q("SELECT * FROM messages WHERE conversation_id=?", (c["id"],))
        )
        t = self.sup.get(r["task_id"])
        self.assertEqual(t["prompt"], "[deleted by owner]")
        self.assertNotIn("widgets", t["checkpoint"])
        self.assertFalse(os.path.exists(t["output_path"]))

    def test_delete_roundtable(self):
        ensure_schema(self.store)
        rec = roundtable.save(
            self.store,
            self.p["id"],
            {
                "mode": "general",
                "objective": "a long enough objective",
                "deliverable": "memo",
                "roster": ["openai"],
                "sharing_ack": True,
            },
        )
        self.store.x(
            "INSERT INTO roundtable_events(rt_id,event_id,kind,content,created) VALUES(?,?,?,?,?)",
            (rec["id"], "ev_x", "message", "hello", time.time()),
        )
        out = deletion.delete_roundtable(self.store, rec["id"])
        self.assertEqual(out["events"], 1)
        self.assertIsNone(roundtable.get(self.store, rec["id"]))
        with self.assertRaises(KeyError):
            deletion.delete_roundtable(self.store, rec["id"])

    def test_a6_a7_delete_conversation_scrubs_team_plan_and_staged_photos(self):
        from aesop_studio import plan, team

        c = self.svc.new_conversation(self.p["id"])
        build = "tsk_build01"
        review = "tsk_rev01"
        fix = "tsk_fix01"
        chat_cwd = str(self.tmp / "chatdir")
        Path(chat_cwd).mkdir(parents=True, exist_ok=True)
        out_log = self.tmp / "logs" / "build.out"
        out_log.parent.mkdir(parents=True, exist_ok=True)
        out_log.write_text("secret build prompt", encoding="utf-8")
        now = time.time()
        for tid, prompt in (
            (build, "build me"),
            (review, "review it"),
            (fix, "fix it"),
        ):
            self.store.x(
                "INSERT INTO tasks(id,project_id,provider,prompt,state,cwd,output_path,created,checkpoint) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    tid,
                    self.p["id"],
                    "simulated",
                    prompt,
                    "COMPLETED",
                    chat_cwd,
                    str(out_log),
                    now,
                    "{}",
                ),
            )
        team._put(
            self.store,
            build,
            {
                "build_task": build,
                "review_task": review,
                "fix_task": fix,
                "state": "DONE",
                "round": 1,
                "tests": {"state": "WAITING"},
            },
        )
        team._put(
            self.store,
            fix,
            {
                "build_task": fix,
                "state": "NO_REVIEW",
                "round": 2,
                "tests": {"state": "WAITING"},
            },
        )
        build_plan = plan.add_for_task(self.store, self.p["id"], build, "build me")
        owner_plan = plan.add(self.store, self.p["id"], "owner todo", source="owner")
        edited_plan = plan.add_for_task(self.store, self.p["id"], review, "review it")
        plan.update(
            self.store, self.p["id"], edited_plan["id"], content="owner edited step"
        )
        photo_dir = Path(chat_cwd) / ".aesop" / "photos" / build
        photo_dir.mkdir(parents=True)
        (photo_dir / "photo1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        other = self.svc.new_conversation(self.p["id"])
        self.store.x(
            "INSERT INTO messages(id,conversation_id,role,content,meta,status,created) VALUES(?,?,?,?,?,?,?)",
            (
                "msg_build_user",
                c["id"],
                "user",
                "build me",
                json.dumps({"work": True}),
                "saved",
                now - 0.01,
            ),
        )
        self.store.x(
            "INSERT INTO messages(id,conversation_id,role,content,meta,status,created) VALUES(?,?,?,?,?,?,?)",
            (
                "msg_build_asst",
                c["id"],
                "assistant",
                "",
                json.dumps({"task_id": build, "work": True}),
                "generated",
                now - 0.005,
            ),
        )
        self.store.x(
            "INSERT INTO messages(id,conversation_id,role,content,meta,status,created) VALUES(?,?,?,?,?,?,?)",
            (
                "msg_1",
                c["id"],
                "user",
                "go",
                json.dumps({"task_id": build}),
                "generated",
                now,
            ),
        )
        self.store.x(
            "INSERT INTO messages(id,conversation_id,role,content,meta,status,created) VALUES(?,?,?,?,?,?,?)",
            ("msg_o", other["id"], "user", "stay", "{}", "generated", now),
        )
        deletion.delete_conversation(self.store, self.svc, self.p["id"], c["id"])
        for tid in (build, review, fix):
            t = self.store.one("SELECT prompt FROM tasks WHERE id=?", (tid,))
            self.assertEqual(t["prompt"], "[deleted by owner]")
            self.assertIsNone(
                self.store.one("SELECT k FROM kv WHERE k=?", (f"team:{tid}",))
            )
        self.assertIsNone(
            self.store.one("SELECT id FROM plan_items WHERE id=?", (build_plan["id"],))
        )
        self.assertIsNotNone(
            self.store.one("SELECT id FROM plan_items WHERE id=?", (owner_plan["id"],))
        )
        self.assertIsNotNone(
            self.store.one("SELECT id FROM plan_items WHERE id=?", (edited_plan["id"],))
        )
        self.assertFalse(photo_dir.exists())
        self.assertIsNotNone(
            self.store.one("SELECT id FROM conversations WHERE id=?", (other["id"],))
        )

    def test_a6_chat_work_plan_deleted_uses_composer_text_not_task_payload(self):
        from aesop_studio import plan

        prefix = "[Studio: work in the project folder. You may edit files here.]\n\n"
        composer = "fix the widget layout"
        tid = "tsk_chatwork"
        c = self.svc.new_conversation(self.p["id"])
        now = time.time()
        self.store.x(
            "INSERT INTO tasks(id,project_id,provider,prompt,state,cwd,output_path,created,checkpoint) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                tid,
                self.p["id"],
                "simulated",
                prefix + composer,
                "COMPLETED",
                str(self.tmp / "p"),
                str(self.tmp / "out.txt"),
                now,
                "{}",
            ),
        )
        self.store.x(
            "INSERT INTO messages(id,conversation_id,role,content,meta,status,created) VALUES(?,?,?,?,?,?,?)",
            (
                "msg_user",
                c["id"],
                "user",
                composer,
                json.dumps({"work": True}),
                "saved",
                now,
            ),
        )
        self.store.x(
            "INSERT INTO messages(id,conversation_id,role,content,meta,status,created) VALUES(?,?,?,?,?,?,?)",
            (
                "msg_asst",
                c["id"],
                "assistant",
                "",
                json.dumps({"task_id": tid, "work": True}),
                "generated",
                now + 0.001,
            ),
        )
        chat_plan = plan.add_for_task(self.store, self.p["id"], tid, composer)
        self.store.x(
            "INSERT INTO messages(id,conversation_id,role,content,meta,status,created) VALUES(?,?,?,?,?,?,?)",
            (
                "msg_link",
                c["id"],
                "user",
                "go",
                json.dumps({"task_id": tid}),
                "generated",
                now + 0.002,
            ),
        )
        deletion.delete_conversation(self.store, self.svc, self.p["id"], c["id"])
        self.assertIsNone(
            self.store.one("SELECT id FROM plan_items WHERE id=?", (chat_plan["id"],))
        )

    def test_a6_untouched_plan_deleted_when_label_truncation_ends_on_whitespace(self):
        from aesop_studio import plan

        pad = "x" * 153
        composer = f"{pad} tail"
        tid = "tsk_ws_trunc"
        now = time.time()
        self.store.x(
            "INSERT INTO tasks(id,project_id,provider,prompt,state,cwd,output_path,created,checkpoint) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                tid,
                self.p["id"],
                "simulated",
                composer,
                "COMPLETED",
                str(self.tmp / "p"),
                str(self.tmp / "out.txt"),
                now,
                "{}",
            ),
        )
        build_plan = plan.add_for_task(self.store, self.p["id"], tid, composer)
        c = self.svc.new_conversation(self.p["id"])
        self.store.x(
            "INSERT INTO messages(id,conversation_id,role,content,meta,status,created) VALUES(?,?,?,?,?,?,?)",
            (
                "msg_ws",
                c["id"],
                "user",
                composer,
                json.dumps({"task_id": tid}),
                "generated",
                now,
            ),
        )
        deletion.delete_conversation(self.store, self.svc, self.p["id"], c["id"])
        self.assertIsNone(
            self.store.one("SELECT id FROM plan_items WHERE id=?", (build_plan["id"],))
        )

    def test_a6_untouched_plan_deleted_when_composer_has_internal_whitespace(self):
        from aesop_studio import plan

        composer = "fix   the\n\twidget"
        tid = "tsk_ws_int"
        now = time.time()
        self.store.x(
            "INSERT INTO tasks(id,project_id,provider,prompt,state,cwd,output_path,created,checkpoint) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                tid,
                self.p["id"],
                "simulated",
                composer,
                "COMPLETED",
                str(self.tmp / "p"),
                str(self.tmp / "out.txt"),
                now,
                "{}",
            ),
        )
        build_plan = plan.add_for_task(self.store, self.p["id"], tid, composer)
        c = self.svc.new_conversation(self.p["id"])
        self.store.x(
            "INSERT INTO messages(id,conversation_id,role,content,meta,status,created) VALUES(?,?,?,?,?,?,?)",
            (
                "msg_int",
                c["id"],
                "user",
                composer,
                json.dumps({"task_id": tid}),
                "generated",
                now,
            ),
        )
        deletion.delete_conversation(self.store, self.svc, self.p["id"], c["id"])
        self.assertIsNone(
            self.store.one("SELECT id FROM plan_items WHERE id=?", (build_plan["id"],))
        )

    def test_a6_untouched_build_plan_deleted_without_concurrent_edit(self):
        from aesop_studio import plan

        composer = "build me"
        tid = "tsk_del_ok"
        now = time.time()
        self.store.x(
            "INSERT INTO tasks(id,project_id,provider,prompt,state,cwd,output_path,created,checkpoint) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                tid,
                self.p["id"],
                "simulated",
                composer,
                "COMPLETED",
                str(self.tmp / "p"),
                str(self.tmp / "out.txt"),
                now,
                "{}",
            ),
        )
        build_plan = plan.add_for_task(self.store, self.p["id"], tid, composer)
        c = self.svc.new_conversation(self.p["id"])
        self.store.x(
            "INSERT INTO messages(id,conversation_id,role,content,meta,status,created) VALUES(?,?,?,?,?,?,?)",
            (
                "msg_del",
                c["id"],
                "user",
                composer,
                json.dumps({"task_id": tid}),
                "generated",
                now,
            ),
        )
        deletion.delete_conversation(self.store, self.svc, self.p["id"], c["id"])
        self.assertIsNone(
            self.store.one("SELECT id FROM plan_items WHERE id=?", (build_plan["id"],))
        )

    def test_a6_concurrent_plan_edit_survives_delete(self):
        from aesop_studio import plan

        tid = "tsk_concur"
        now = time.time()
        self.store.x(
            "INSERT INTO tasks(id,project_id,provider,prompt,state,cwd,output_path,created,checkpoint) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                tid,
                self.p["id"],
                "simulated",
                "build me",
                "COMPLETED",
                str(self.tmp / "p"),
                str(self.tmp / "out.txt"),
                now,
                "{}",
            ),
        )
        composer = "build me"
        build_plan = plan.add_for_task(self.store, self.p["id"], tid, composer)
        c = self.svc.new_conversation(self.p["id"])
        self.store.x(
            "INSERT INTO messages(id,conversation_id,role,content,meta,status,created) VALUES(?,?,?,?,?,?,?)",
            (
                "msg_c",
                c["id"],
                "user",
                composer,
                json.dumps({"task_id": tid}),
                "generated",
                now,
            ),
        )
        original_tx = self.store.tx

        class _ConnProxy:
            __slots__ = ("_c",)

            def __init__(self, c):
                self._c = c

            def execute(self, sql, args=()):
                if isinstance(sql, str) and sql.startswith(
                    "DELETE FROM plan_items WHERE id=? AND content"
                ):
                    self._c.execute(
                        "UPDATE plan_items SET content=? WHERE id=?",
                        ("owner edited between read and delete", args[0]),
                    )
                return self._c.execute(sql, args)

            def __getattr__(self, name):
                return getattr(self._c, name)

        @contextmanager
        def tx_hook():
            with original_tx() as c:
                yield _ConnProxy(c)

        self.store.tx = tx_hook
        try:
            deletion.delete_conversation(self.store, self.svc, self.p["id"], c["id"])
        finally:
            self.store.tx = original_tx
        self.assertIsNotNone(
            self.store.one("SELECT id FROM plan_items WHERE id=?", (build_plan["id"],))
        )


if __name__ == "__main__":
    unittest.main()
