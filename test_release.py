import asyncio
from contextlib import closing
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from local_settings import claude_ip
from projects import model_command, project_command, project_row
from record_store import discussion_folder
import roundtable as rt


class PortableReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        env = patch.dict(os.environ, ROUNDTABLE_HOME=temporary.name)
        env.start()
        self.addCleanup(env.stop)
        self.db = rt.database()
        self.addCleanup(self.db.close)

    def test_migrate_legacy_files_and_remove_exactly_one_discussion(self):
        legacy = Path(os.environ["ROUNDTABLE_HOME"]) / "exports" / "old"
        legacy.mkdir(parents=True)
        (legacy / "方案.pdf").write_bytes(b"%PDF-1.7")
        self.db.execute("INSERT INTO sessions(id,project,topic,state) VALUES('old','默认','旧标题','consensus')")
        self.db.execute("INSERT INTO calls(session,stage,agent,reply,ended) VALUES('old','独立提案','codex','原回复',1)")
        cid = self.db.execute("SELECT id FROM calls WHERE session='old'").fetchone()[0]
        self.db.execute("INSERT INTO tool_permissions(call_id,details,can_allow) VALUES(?,'{}',1)", (cid,))
        with closing(rt.database()):
            folder = discussion_folder("默认","old")
            self.assertEqual((folder / "方案.pdf").read_bytes(), b"%PDF-1.7")
            self.assertIn("原回复", (folder / "讨论记录.md").read_text(encoding="utf-8"))
        child, _, _ = rt.prepare_topic(self.db, "后续", "old", "默认")
        rt.finish(self.db, child, "chat")
        project_command(self.db, "默认", ["add", "另一 项目"])
        other, _, _ = rt.prepare_topic(self.db, "另一个项目的记录", None, "另一 项目")
        rt.finish(self.db, other, "chat")
        shutil.rmtree(folder)
        with closing(rt.database()) as db:
            self.assertIsNone(rt.session(db, child)["parent"])
            self.assertEqual(rt.session(db, other, "另一 项目")["state"], "chat")
            self.assertEqual(db.execute("SELECT count(*) FROM calls WHERE session='old'").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT count(*) FROM tool_permissions").fetchone()[0],0)
            self.assertFalse(folder.exists())

    def test_interrupted_ready_folder_gets_saved_partial_reply(self):
        sid, _, _ = rt.prepare_topic(self.db, "中断", None, "默认")
        self.db.execute("INSERT INTO calls(session,stage,agent,reply,owner) VALUES(?,'独立提案','codex','部分回复',1234)", (sid,))
        with patch("roundtable.process_alive", return_value=False), closing(rt.database()) as db:
            self.assertEqual(rt.session(db, sid)["state"],"incomplete")
        self.assertIn("部分回复",(discussion_folder("默认",sid)/"讨论记录.md").read_text(encoding="utf-8"))

    def test_local_claude_configuration_starts_empty_and_off_clears_seats(self):
        self.assertEqual(claude_ip(),"")
        model_command(self.db, "默认", ["claude","ip","203.0.113.10"])
        with patch("projects.check_claude"):
            model_command(self.db, "默认", ["claude","on"])
        self.assertTrue(project_row(self.db, "默认")["claude_enabled"])
        model_command(self.db, "默认", ["claude","ip","off"])
        self.assertFalse(project_row(self.db, "默认")["claude_enabled"])
        self.assertEqual(claude_ip(),"")

    def test_removed_record_cannot_start_late_call(self):
        sid, _, _ = rt.prepare_topic(self.db, "旧讨论", None, "默认")
        rt.finish(self.db, sid, "consensus")
        folder = discussion_folder("默认", sid)
        expected = Path.is_dir
        def remove_after_check(path):
            if path == folder and expected(path):
                shutil.rmtree(path)
                with closing(rt.database()):
                    pass
                return True
            return expected(path)
        with patch.object(Path,"is_dir",remove_after_check), patch("roundtable.invoke") as invoke:
            self.assertIsNone(asyncio.run(rt.call(self.db, sid, "图文 PDF 排版", "gemini", "test", "test")))
        invoke.assert_not_called()
        self.assertEqual(self.db.execute("SELECT count(*) FROM calls WHERE session=?", (sid,)).fetchone()[0],0)

    def test_moderator_routes_candidate_and_preserves_readonly_reviewer(self):
        async def client(agent, prompt, ballot=False, schema=None, **opts):
            if ballot:
                return '{"vote":"accept","reason":"同意"}', {}
            if schema:
                return '{"plan":"共识","tasks":[{"owner":"codex","task":"做","acceptance":"测试"}]}', {}
            return "回复", {}
        with patch("roundtable.invoke", side_effect=client), patch("roundtable.binary", return_value="/model"):
            sid = asyncio.run(rt.begin(self.db, "讨论", moderator="gemini"))
        self.assertEqual(rt.session(self.db, sid)["state"], "consensus")
        lead = self.db.execute("SELECT agent FROM calls WHERE session=? AND stage='候选方案 v1'", (sid,)).fetchone()[0]
        self.assertEqual(lead,"gemini")
        self.assertEqual(rt.reviewer_for(lead),"codex")

    def test_snapshot_error_preserves_finished_state(self):
        sid,_,_=rt.prepare_topic(self.db,"无法落盘",None,"默认")
        with patch("roundtable.write_text", side_effect=PermissionError):
            self.assertEqual(rt.finish(self.db,sid,"chat"),"chat")
        row=rt.session(self.db,sid)
        self.assertEqual(row["state"],"chat")
        self.assertIn("无法写入",row["failure"])

    def test_incomplete_single_seat_can_retry_after_timeout(self):
        with patch("roundtable.binary",return_value="/model"), patch("roundtable.invoke",side_effect=asyncio.TimeoutError):
            sid=asyncio.run(rt.begin(self.db,"单聊中断",agent="codex"))
        self.assertEqual(rt.session(self.db,sid)["state"],"incomplete")
        with patch("roundtable.binary",return_value="/model"), patch("roundtable.invoke",return_value=("成功",{})) as call:
            asyncio.run(rt.resume_discussion(self.db,sid,"默认"))
        self.assertEqual(rt.session(self.db,sid)["state"],"chat")
        self.assertEqual(call.await_args.args[0],"codex")
