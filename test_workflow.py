import asyncio
import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import roundtable as app


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {"ROUNDTABLE_HOME": self.tmp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.db = app.database()
        self.addCleanup(self.db.close)
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch("roundtable.binary", return_value="/cli"))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.log = []

    def discuss(self, vote="accept", fail=False, rounds=1):
        async def client(agent, prompt, workspace=None, ballot=False, selected_model=None, on_text=None, **options):
            self.log.append((agent, prompt, workspace))
            if fail and agent == "gemini":
                raise ValueError("quota")
            if ballot:
                answer = vote if agent == "gemini" else "accept"
                text = '{"vote":"%s","reason":"check baseline"}' % answer
            elif "拟定一份" in prompt:
                text = json.dumps({"plan":"unified candidate", "tasks":[
                    {"owner": a, "task": a+" work", "acceptance":"run test"} for a in ("codex", "gemini")]})
            else:
                text = agent + " observation"
            return text, {"total": 10}
        with patch("roundtable.invoke", client):
            return asyncio.run(app.begin(self.db, "original question", rounds=rounds))

    def test_disputed_run_includes_both_views_and_cannot_execute(self):
        sid = self.discuss(vote="object", rounds=2)
        self.assertEqual(app.session(self.db, sid)["state"], "disputed")
        self.assertEqual(len(self.log), 10)
        self.assertEqual(self.log[0][1], self.log[1][1])
        self.assertNotIn("observation", self.log[0][1])
        for _, prompt, _ in self.log[2:4]:
            self.assertIn("codex observation", prompt)
            self.assertIn("gemini observation", prompt)
        self.assertEqual(self.log[5][1], self.log[6][1])
        self.assertIn("check baseline", self.log[7][1])
        with self.assertRaises(ValueError):
            asyncio.run(app.implement(self.db, sid, self.tmp.name))

    def test_three_seats_require_each_vote_and_claude_synthesizes(self):
        async def immediate(func):
            return func()
        self.db.execute("UPDATE projects SET claude_enabled=1")
        with patch("roundtable.check_claude"), patch("roundtable.asyncio.to_thread", immediate):
            sid = self.discuss()
            self.assertEqual(app.session(self.db,sid)["state"], "consensus")
            self.assertEqual(len(self.log),11)
            self.assertEqual(self.log[6][0],"claude")
            self.assertEqual(self.log[-1][0],"gemini")
            self.assertIn("全体通过的原文", self.log[-1][1])
            self.log.clear()
            sid = self.discuss(vote="object")
            self.assertEqual(app.session(self.db,sid)["state"], "disputed")
        with patch("roundtable.check_claude",side_effect=ValueError("IP 不匹配")), patch("roundtable.asyncio.to_thread",immediate):
            self.log.clear()
            sid = self.discuss()
            self.assertEqual({a for a,_,_ in self.log},{"codex","gemini"})
            record = app.session(self.db,sid)
            self.assertEqual(record["state"],"consensus")
            self.assertIn("IP",json.loads(record["settings"])["notice"])
            self.assertNotIn("claude",json.loads(record["settings"])["models"])

    def test_blocked_handoff_stops_remaining_workers(self):
        sid = self.discuss()
        with patch("roundtable.invoke",return_value=('{"status":"blocked","report":"test failed"}',{})) as invoke:
            self.assertEqual(asyncio.run(app.implement(self.db,sid,self.tmp.name)),"inspect")
            self.assertEqual(invoke.await_count,1)
            self.assertIn("test failed",app.session(self.db,sid)["failure"])

    def test_claude_disconnect_during_vote_retains_two_votes_for_resume(self):
        self.db.execute("UPDATE projects SET claude_enabled=1")
        disconnected = True
        async def client(agent, prompt, ballot=False, schema=None, **kwargs):
            if ballot:
                if disconnected and agent == "claude":
                    raise ValueError("Claude 出口 IP 不匹配")
                return '{"vote":"accept","reason":"同意本版"}', {}
            if schema:
                return json.dumps({"plan":"方案","tasks":[{"owner":"codex","task":"实施","acceptance":"核对结果"}]}), {}
            return agent + " 回复", {}
        with patch("roundtable.check_claude"), patch("roundtable.invoke", side_effect=client) as invoke:
            sid = asyncio.run(app.begin(self.db, "测试投票中断"))
            self.assertEqual(app.session(self.db, sid)["state"], "incomplete")
            rows = self.db.execute("SELECT agent,error FROM calls WHERE session=? AND stage='表决 v1'", (sid,))
            self.assertEqual(dict(rows), {"codex":None, "gemini":None, "claude":"Claude 出口 IP 不匹配"})
            with self.assertRaises(ValueError):
                asyncio.run(app.implement(self.db, sid, self.tmp.name))
            disconnected = False
            invoke.reset_mock()
            asyncio.run(app.resume_discussion(self.db, sid, "默认"))
            self.assertEqual(app.session(self.db, sid)["state"], "consensus")
            self.assertEqual([(c.args[0],c.kwargs["ballot"]) for c in invoke.await_args_list],
                             [("claude",True), ("gemini",False)])

    def test_invalid_ballot_is_incomplete_not_a_substantive_disagreement(self):
        sid = self.discuss(vote="invalid")
        self.assertEqual(app.session(self.db, sid)["state"], "incomplete")

    def test_failed_party_preserves_other_reply(self):
        sid = self.discuss(fail=True)
        self.assertEqual(app.session(self.db, sid)["state"], "incomplete")
        self.assertEqual(len(self.log), 2)
        self.assertIn("codex observation", app.history(self.db, sid))
        with self.assertRaises(ValueError):
            asyncio.run(app.implement(self.db, sid, self.tmp.name))

    def test_resume_only_retries_missing_seat_and_preserves_peer_review(self):
        sid = self.discuss(fail=True)
        events = []
        async def complete(agent, prompt, ballot=False, schema=None, **kwargs):
            events.append((agent,prompt))
            if ballot:
                return '{"vote":"accept","reason":"clear"}',{}
            if schema:
                return json.dumps({"plan":"approved","tasks":[{"owner":"codex","task":"build","acceptance":"verify"}]}),{}
            return ("Gemini final" if "最终执笔人" in prompt else agent+" reply"),{}
        with patch("roundtable.invoke",complete):
            asyncio.run(app.resume_discussion(self.db,sid,"默认"))
        self.assertEqual(app.session(self.db,sid)["state"],"consensus")
        self.assertEqual([a for a,prompt in events if "独立给出你的方案" in prompt], ["gemini"])
        for _,prompt in events[1:3]:
            self.assertIn("codex observation",prompt)
            self.assertIn("gemini reply",prompt)
        self.assertIn("全体通过的原文",events[-1][1])
        self.assertEqual(self.db.execute("SELECT count(*) FROM calls WHERE session=? AND error IS NOT NULL",(sid,)).fetchone()[0],1)
        with self.assertRaisesRegex(ValueError,"已经完成"):
            asyncio.run(app.resume_discussion(self.db,sid,"默认"))

    def test_failed_writer_can_retry_without_repeating_ballots(self):
        sid=self.discuss()
        self.db.execute("UPDATE calls SET error='timeout',reply=NULL WHERE session=? AND stage='最终方案撰写'",(sid,))
        with patch("roundtable.invoke",return_value=("final",{})) as invoke:
            asyncio.run(app.resume_discussion(self.db,sid,"默认"))
        self.assertEqual(invoke.await_count,1)
        self.assertEqual(invoke.call_args.args[0],"gemini")
        self.assertEqual(app.session(self.db,sid)["state"],"consensus")

    def test_cross_review_keeps_evidence_and_only_counts_valid_votes(self):
        seen = {}
        async def answer(agent, prompt, ballot=False, schema=None, **kwargs):
            if ballot:
                return json.dumps({"vote":"object" if agent == "gemini" else "accept", "reason":"Check blank samples"}), {}
            if schema:
                return json.dumps({"plan":"Candidate", "tasks":[{"owner":"codex","task":"Build","acceptance":"Test"}],
                                   "dispositions":[{"id":"E1.1","response":"Add blank samples before deciding"}]}), {}
            if "完整候选" in prompt:
                seen[agent] = prompt
                if agent == "gemini":
                    return "Free-form alternative", {}
                return json.dumps({"items":[
                    {"claim":"Noise could explain the result","kind":"observation","source":"raw.csv:L2","blocking":True,
                     "check":"Check that blanks stay below 2 mV"},
                    {"claim":"An unchecked assertion","kind":"reference","blocking":True}]}), {}
            return {"codex":"Blank sample proposal","gemini":"Repeated measures proposal"}[agent], {}
        with patch("roundtable.invoke", side_effect=answer):
            sid = asyncio.run(app.begin(self.db, "Use the same baseline", rounds=1))
        for agent, prompt in seen.items():
            self.assertIn("Blank sample proposal", prompt)
            self.assertIn("Repeated measures proposal", prompt)
            self.assertIn("Use the same baseline", prompt)
            self.assertNotIn(agent, prompt)
        review = app.discussion_review(self.db, sid)
        self.assertEqual(review["votes"], {"codex":"accept","gemini":"object"})
        self.assertEqual(review["original"], ["gemini"])
        item, downgraded = review["items"]
        self.assertEqual((item["id"], item["agent"], item["response"]), ("E1.1", "codex", "Add blank samples before deciding"))
        self.assertFalse(downgraded["blocking"])
        self.assertIn("评议者报告", app.transcript(self.db, sid, "默认"))

    def test_changed_input_blocks_resuming_without_spending_calls(self):
        with tempfile.TemporaryDirectory() as workspace:
            source = Path(workspace)
            material = source / "source.txt"
            material.write_text("baseline", encoding="utf-8")
            app.project_command(self.db, "默认", ["path", str(source)])
            sid = self.discuss(fail=True)
            (source / ".env").write_text("ignore this", encoding="utf-8")
            with patch("roundtable.invoke", return_value=("temporary reply", {})) as invoke:
                asyncio.run(app.resume_discussion(self.db, sid, "默认"))
                self.assertGreater(invoke.await_count, 0)
            material.write_text("new baseline", encoding="utf-8")
            with patch("roundtable.invoke") as invoke:
                asyncio.run(app.resume_discussion(self.db, sid, "默认"))
                invoke.assert_not_called()
                record = app.session(self.db, sid)
                self.assertEqual(record["state"], "incomplete")
                self.assertEqual(json.loads(record["settings"])["input_change"]["paths"], ["source.txt"])
                with self.assertRaisesRegex(ValueError, "关联讨论"):
                    asyncio.run(app.resume_discussion(self.db, sid, "默认"))
            self.assertIn("codex observation", app.transcript(self.db, sid, "默认"))

    @unittest.skipUnless(shutil.which("git"), "Git required for previews")
    def test_preview_creates_applicable_patch_without_editing_original(self):
        for versioned in (True, False):
            with self.subTest(versioned=versioned), tempfile.TemporaryDirectory() as workspace:
                source = Path(workspace).resolve()
                original = source / "source.txt"
                original.write_bytes(b"baseline\n")
                def git(*args):
                    return subprocess.check_output(["git", "-C", str(source), *args], stderr=subprocess.PIPE)
                if versioned:
                    git("init", "-q")
                    git("add", ".")
                    git("-c", "user.name=Roundtable", "-c", "user.email=roundtable@example.invalid", "commit", "-qm", "baseline")
                sid = self.discuss()
                if versioned:
                    original.write_bytes(b"dirty\n")
                    with self.assertRaisesRegex(ValueError, "未提交"):
                        asyncio.run(app.implement(self.db, sid, source, preview=True))
                    self.assertEqual(app.session(self.db, sid)["state"], "consensus")
                    self.assertEqual(original.read_bytes(), b"dirty\n")
                    original.write_bytes(b"baseline\n")
                calls = []
                async def execute(agent, prompt, workspace, reviewing, **kwargs):
                    calls.append((workspace, reviewing))
                    if not reviewing:
                        (workspace / "source.txt").write_bytes(b"updated\n")
                        (workspace / "added.bin").write_bytes(b"\x00\x03")
                    self.assertEqual(original.read_bytes(), b"baseline\n")
                    return '{"status":"done","report":"Verified"}', {}
                with patch("roundtable.invoke", side_effect=execute):
                    self.assertEqual(asyncio.run(app.implement(self.db, sid, source, preview=True)), "returned")
                self.assertNotEqual(calls[0][0], source)
                self.assertEqual([reviewing for _, reviewing in calls], [False,False,True])
                self.assertFalse(calls[0][0].exists())
                self.assertEqual(original.read_bytes(), b"baseline\n")
                self.assertFalse((source / "added.bin").exists())
                preview = app.discussion_folder("默认", sid) / app.PATCH_NAME
                git("apply", "--check", str(preview))
                if versioned:
                    self.assertEqual(git("status", "--short"), b"")
                    self.assertEqual(git("worktree", "list", "--porcelain").count(b"worktree "), 1)

    def test_overlapping_implementation_is_rejected(self):
        one, two = self.discuss(), self.discuss()
        self.db.execute("UPDATE sessions SET state='implementing',workspace=? WHERE id=?", (self.tmp.name,one))
        child = Path(self.tmp.name) / "child"
        child.mkdir()
        with self.assertRaisesRegex(ValueError,"正在被讨论"):
            asyncio.run(app.implement(self.db,two,str(child)))
        self.assertEqual(app.session(self.db,two)["state"], "consensus")

    def test_failed_review_keeps_reports_and_blocks_completion(self):
        sid = self.discuss()
        async def execute(agent, prompt, reviewing=False, **kw):
            return json.dumps({"status":"blocked" if reviewing else "done", "report":"checked"}), {}
        with patch("roundtable.invoke", execute):
            self.assertEqual(asyncio.run(app.implement(self.db,sid,self.tmp.name)),"inspect")
        record = app.transcript(self.db,sid,"默认")
        self.assertIn("集成复核",record)
        self.assertIn("blocked",record)

    def test_implement_once_in_selected_directory(self):
        sid = self.discuss()
        self.assertEqual(app.session(self.db, sid)["state"], "consensus")
        destinations = []
        async def execute(agent, prompt, workspace=None, ballot=False, selected_model=None, on_text=None, **options):
            destinations.append((agent, str(workspace), options["reviewing"]))
            if agent == "gemini":
                self.assertIn("codex finished", prompt)
            self.assertIn("unified candidate", prompt)
            return json.dumps({"status":"done", "report":agent+" finished"}), {}
        with patch("roundtable.invoke", execute):
            asyncio.run(app.implement(self.db, sid, self.tmp.name))
            with self.assertRaises(ValueError):
                asyncio.run(app.implement(self.db, sid, self.tmp.name))
        self.assertEqual(destinations, [(a, str(Path(self.tmp.name).resolve()), review) for a, review in [("codex",False),("gemini",False),("codex",True)]])


if __name__ == "__main__":
    unittest.main()
