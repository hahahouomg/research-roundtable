import asyncio
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import roundtable as rt
from projects import model_command, project_command, project_row, workspace
from quotas import claude_windows, codex_windows, read_claude


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

    def test_claude_quota_never_starts_cli_if_ip_check_fails(self):
        async def immediate(func):
            return func()
        with patch("quotas.asyncio.to_thread",immediate), patch("quotas.check_claude",side_effect=ValueError("IP 不匹配")), patch("quotas.asyncio.create_subprocess_exec") as launch:
            with self.assertRaisesRegex(ValueError,"IP 不匹配"):
                asyncio.run(read_claude("/claude"))
        launch.assert_not_called()

    @unittest.skipIf(os.name == "nt", "POSIX executable fixture")
    def test_switch_off_then_on_terminates_the_old_claude_process(self):
        folder = Path(os.environ["ROUNDTABLE_HOME"])
        cli, pidfile = folder/"claude", folder/"worker.pid"
        cli.write_text('#!/bin/sh\necho "$$" > "$TEST_CLAUDE_PID"\nexec sleep 30\n')
        cli.chmod(0o700)
        async def switch_during_call():
            sid, _, _ = rt.prepare_topic(self.db, "测试开关", None, "默认")
            task = asyncio.create_task(rt.call(self.db, sid, "独立提案", "claude", "测试", "example"))
            for _ in range(150):
                if pidfile.exists() and pidfile.read_text().strip():
                    break
                await asyncio.sleep(0.01)
            pid = int(pidfile.read_text())
            model_command(self.db, "默认", ["claude", "off"])
            model_command(self.db, "默认", ["claude", "on"])
            self.assertIsNone(await asyncio.wait_for(task, 3))
            err, ended = self.db.execute("SELECT error,ended FROM calls WHERE session=?", (sid,)).fetchone()
            self.assertIn("关闭", err)
            self.assertIsNotNone(ended)
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
        with patch.dict(os.environ, ROUNDTABLE_CLAUDE_BIN=str(cli), TEST_CLAUDE_PID=str(pidfile)), \
             patch("projects.check_claude"), patch("providers.check_claude"), \
             patch("providers.CLAUDE_CHECK_INTERVAL", 0.02), redirect_stdout(io.StringIO()):
            model_command(self.db, "默认", ["claude", "on"])
            asyncio.run(switch_during_call())

    def test_claude_quota_uses_only_reported_windows(self):
        packet = {"type":"control_response", "response":{"request_id":"quota", "response":{
            "subscription_type":"pro", "rate_limits":{"five_hour":{"utilization":12,"resets_at":"2026-11-24T12:00:00Z"},
            "seven_day":{"utilization":0}, "seven_day_opus":None}}}}
        import json
        self.assertEqual(claude_windows(json.dumps(packet))["windows"], [
            {"label":"5 小时","percent":88,"reset":"2026-11-24T12:00:00Z"},
            {"label":"7 天","percent":100,"reset":None}])
        with self.assertRaises(ValueError):
            claude_windows(b'{"type":"control_response","response":{}}')

    def test_previous_trash_restored_without_losing_files_or_history(self):
        from local_ui import state
        with redirect_stdout(io.StringIO()):
            project_command(self.db,"默认",["add","A"])
            root,_,_=rt.prepare_topic(self.db,"旧记录",None,"A")
        target = workspace(project_row(self.db, "A")) / "keep.txt"
        target.write_text("keep")
        self.db.execute("UPDATE projects SET trashed=1 WHERE name='A'")
        self.db.execute("UPDATE sessions SET trash_root=id")
        self.db.execute("PRAGMA user_version=0")
        rt.setup(self.db)
        self.assertIn("A",state(self.db,"默认")["projects"])
        self.assertEqual(state(self.db,"A")["sessions"][0]["id"],root)
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
