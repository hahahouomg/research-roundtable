import asyncio
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import roundtable as rt
from projects import project_command
from quotas import codex_windows


class Controls(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        env = patch.dict(os.environ, ROUNDTABLE_HOME=t.name)
        env.start()
        self.addCleanup(env.stop)
        self.db = rt.database()
        self.addCleanup(self.db.close)

    def test_quota_uses_vendor_windows(self):
        row = {"rateLimits":{"planType":"pro","primary":{"usedPercent":23,"windowDurationMins":300,"resetsAt":123}}}
        self.assertEqual(codex_windows(row)["windows"], [{"label":"codex · 5 小时","percent":77,"reset":123}])

    def test_trash_and_restore_preserve_files_and_branches(self):
        from projects import move_trash
        from local_ui import state
        with redirect_stdout(io.StringIO()):
            project_command(self.db,"默认",["add","A"])
            root,_,_=rt.prepare_topic(self.db,"根",None,"A")
            with self.assertRaises(ValueError):
                move_trash(self.db,"A","project","A",False)
            self.db.execute("UPDATE sessions SET state='chat' WHERE id=?",(root,))
            child,_,_=rt.prepare_topic(self.db,"追问",root,"A")
            self.db.execute("UPDATE sessions SET state='chat' WHERE id=?",(child,))
        target=Path(os.environ["ROUNDTABLE_HOME"])/"workspaces/A/keep.txt"
        target.write_text("keep")
        move_trash(self.db,"A","session",root,False)
        self.assertEqual(state(self.db,"A")["sessions"],[])
        move_trash(self.db,"A","session",root,True)
        self.assertEqual(len(state(self.db,"A")["sessions"]),2)
        move_trash(self.db,"A","project","A",False)
        self.assertNotIn("A",state(self.db,"默认")["projects"])
        move_trash(self.db,"默认","project","A",True)
        self.assertEqual(len(state(self.db,"A")["sessions"]),2)
        self.assertEqual(target.read_text(),"keep")

    def test_stopping_retains_partial_and_cancels_worker(self):
        async def run():
            reached = asyncio.Event()
            killed = asyncio.Event()
            async def fake(agent,prompt,*,on_text,**kwargs):
                on_text("已到达的片段")
                reached.set()
                try:
                    await asyncio.sleep(20)
                finally:
                    killed.set()
            sid,context,models = rt.prepare_topic(self.db,"示例",None,"默认")
            with patch("roundtable.invoke",fake):
                task = asyncio.create_task(rt.run_topic(self.db,sid,context,models,"gemini",1,False))
                await asyncio.wait_for(reached.wait(),1)
                rt.request_stop(self.db,sid,"默认")
                await asyncio.wait_for(task,3)
            self.assertTrue(killed.is_set())
            self.assertEqual(rt.session(self.db,sid)["state"],"stopped")
            self.assertIn("已到达的片段",rt.history(self.db,sid))
        with redirect_stdout(io.StringIO()):
            asyncio.run(run())
