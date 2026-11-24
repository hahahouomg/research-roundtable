import asyncio
import contextlib
import io
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
        async def client(agent, prompt, workspace=None, ballot=False, selected_model=None, on_text=None):
            self.log.append((agent, prompt, workspace))
            if fail and agent == "gemini":
                raise ValueError("quota")
            if ballot:
                answer = vote if agent == "gemini" else "accept"
                text = '{"vote":"%s","reason":"check baseline"}' % answer
            elif "拟定一份" in prompt:
                text = "unified candidate"
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

    def test_implement_once_in_selected_directory(self):
        sid = self.discuss()
        self.assertEqual(app.session(self.db, sid)["state"], "consensus")
        destinations = []
        async def execute(agent, prompt, workspace=None, ballot=False, selected_model=None, on_text=None):
            destinations.append(str(workspace))
            self.assertIn("unified candidate", prompt)
            return "implemented", {}
        with patch("roundtable.invoke", execute):
            asyncio.run(app.implement(self.db, sid, self.tmp.name))
            with self.assertRaises(ValueError):
                asyncio.run(app.implement(self.db, sid, self.tmp.name))
        self.assertEqual(destinations, [str(Path(self.tmp.name).resolve())])


if __name__ == "__main__":
    unittest.main()
