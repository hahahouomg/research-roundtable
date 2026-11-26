import asyncio
import contextlib
import io
import json
import os
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
