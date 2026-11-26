import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import roundtable as rt
from local_ui import state


class ToolPermissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        env = patch.dict(os.environ, {"ROUNDTABLE_HOME": folder.name})
        env.start()
        self.addCleanup(env.stop)
        self.db = rt.database()
        self.addCleanup(self.db.close)
        self.sid, _, _ = rt.prepare_topic(self.db, "授权测试", None, "默认")
        self.started = asyncio.Event()

    def job(self, can_allow=True):
        async def invoke(agent, prompt, on_permission, **opts):
            self.started.set()
            allowed = await on_permission({"title": "Bash", "rawInput": {"command": "python3 check.py"}}, can_allow)
            if not allowed:
                raise ValueError("已拒绝")
            return "verified", {}
        patched = patch("roundtable.invoke", invoke)
        patched.start()
        self.addCleanup(patched.stop)
        return asyncio.create_task(rt.call(self.db, self.sid, "交叉评议", "gemini", "check", "neon", self.folder))

    def pending(self):
        return state(self.db, "默认", self.sid)["selected"]["permissions"]

    async def test_single_use_decision_is_scoped_and_survives_reload(self):
        job = self.job()
        await self.started.wait()
        first, = self.pending()
        self.assertEqual(self.pending(), [first])
        self.assertEqual(first["details"]["rawInput"]["command"], "python3 check.py")
        other, _, _ = rt.prepare_topic(self.db, "其他讨论", None, "默认")
        with self.assertRaises(ValueError):
            rt.decide_tool(self.db, other, "默认", first["id"], "allow")
        rt.decide_tool(self.db, self.sid, "默认", first["id"], "allow")
        with self.assertRaises(ValueError):
            rt.decide_tool(self.db, self.sid, "默认", first["id"], "deny")
        self.assertEqual(await job, "verified")
        self.assertFalse(self.pending())
        self.assertIn("允许一次", rt.transcript(self.db, self.sid, "默认"))

    async def test_no_one_shot_option_can_only_be_declined(self):
        job = self.job(False)
        await self.started.wait()
        req, = self.pending()
        self.assertFalse(req["can_allow"])
        with self.assertRaises(ValueError):
            rt.decide_tool(self.db, self.sid, "默认", req["id"], "allow")
        rt.decide_tool(self.db, self.sid, "默认", req["id"], "deny")
        self.assertIsNone(await job)

    async def test_stop_expires_open_request(self):
        job = self.job()
        await self.started.wait()
        req, = self.pending()
        rt.request_stop(self.db, self.sid, "默认")
        self.assertIsNone(await job)
        with self.assertRaises(ValueError):
            rt.decide_tool(self.db, self.sid, "默认", req["id"], "allow")
        self.assertIn("已失效", rt.transcript(self.db, self.sid, "默认"))

    async def test_interrupted_pdf_expires_its_request_after_consensus(self):
        self.db.execute("UPDATE sessions SET state='consensus' WHERE id=?", (self.sid,))
        cid = self.db.execute("INSERT INTO calls(session,stage,owner) VALUES(?,'图文 PDF 排版',12345)",
                              (self.sid,)).lastrowid
        self.db.execute("INSERT INTO tool_permissions(call_id,details,can_allow) VALUES(?,'{}',1)", (cid,))
        with patch("roundtable.process_alive", return_value=False):
            rt.database().close()
        self.assertEqual(rt.session(self.db, self.sid)["state"], "consensus")
        self.assertIsNotNone(self.db.execute("SELECT ended FROM calls WHERE id=?", (cid,)).fetchone()[0])
        self.assertEqual(self.db.execute("SELECT decision FROM tool_permissions WHERE call_id=?", (cid,)).fetchone()[0],
                         "expired")


class AcpProtocolTests(unittest.IsolatedAsyncioTestCase):
    def test_explicit_sandbox_only_and_review_modes_take_precedence(self):
        from gemini_acp import execution_mode
        with tempfile.TemporaryDirectory() as home, patch("gemini_acp.Path.home", return_value=Path(home)):
            settings = Path(home) / ".gemini/antigravity-cli/settings.json"
            settings.parent.mkdir(parents=True)
            available = {"default", "auto", "accept-edits"}
            settings.write_text('{"toolPermission":"proceed-in-sandbox"}')
            self.assertEqual(execution_mode(available), "default")
            self.assertEqual(execution_mode(available,"cli","accept-edits"),"accept-edits")
            settings.write_text('{"toolPermission":"request-review"}')
            self.assertEqual(execution_mode(available), "default")

    @unittest.skipIf(os.name == "nt", "POSIX executable fixture")
    async def test_sandbox_model_auto_and_allow_once_resume_same_prompt(self):
        from gemini_acp import run
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            exe = root / "agy"
            exe.write_text("""#!/usr/bin/env python3
import json,sys
assert sys.argv[1:3] == ['acp','--sandbox']
def read():
    return json.loads(input())
def event(**data):
    print(json.dumps(dict(jsonrpc='2.0',**data)),flush=True)
for method,result in (
        ('initialize',{}),
        ('session/new',{'sessionId':'s','models':{'currentModelId':'other'},
                        'modes':{'currentModeId':'default','availableModes':[{'id':'auto'}]}}),
        ('session/set_model',{}),('session/set_mode',{})):
    msg=read()
    assert msg['method']==method
    if method=='session/set_model': assert msg['params']['modelId']=='gemini-4-neon-xhigh'
    if method=='session/set_mode': assert msg['params']['modeId']=='auto'
    event(id=msg['id'],result=result)
msg=read()
assert msg['method']=='session/prompt'
tool={'toolCallId':'t','title':'Review file','rawInput':{'path':'report'}}
event(method='session/update',params={'sessionId':'s','update':dict(sessionUpdate='tool_call',**tool)})
event(id=90,method='session/request_permission',params={'sessionId':'s','toolCall':{'toolCallId':'t'},
      'options':[{'kind':'allow_always','optionId':'persistent'},{'kind':'allow_once','optionId':'once'}]})
decision=read()
assert decision['id']==90 and decision['result']['outcome']=={'outcome':'selected','optionId':'once'}
event(method='session/update',params={'sessionId':'s','update':{'sessionUpdate':'agent_message_chunk',
      'content':{'type':'text','text':'verified'}}})
event(id=msg['id'],result={'stopReason':'end_turn','usage':{'totalTokens':10}})
""")
            exe.chmod(0o700)
            async def decide(tool, can_allow):
                self.assertTrue(can_allow)
                self.assertEqual(tool["rawInput"], {"path": "report"})
                await asyncio.sleep(1.1)
                return True
            with patch("gemini_acp.Path.home", return_value=root):
                result, usage = await run(str(exe), root, "test", "gemini-4-neon-xhigh", None, 1,
                                          root / "log", None, decide, None)
            self.assertEqual((result, usage), ("verified", {"total": 10}))
