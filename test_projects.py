import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

APP = Path(__file__).resolve().with_name("roundtable.py")


class ProjectCommands(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.db = self.home / "roundtable.sqlite3"
        self.env = dict(os.environ, ROUNDTABLE_HOME=temp.name, ROUNDTABLE_CODEX_BIN=str(self.home / "codex"),
                        ROUNDTABLE_AGY_BIN=str(self.home / "agy"))

    def cli(self, *args, stdin=None, ok=True):
        proc = subprocess.run([sys.executable, "-X", "utf8", "-B", str(APP), *args], input=stdin,
                              env=self.env, capture_output=True, text=True, encoding="utf-8")
        if ok:
            self.assertEqual(proc.returncode, 0, proc.stderr)
        else:
            self.assertNotEqual(proc.returncode, 0)
        return proc.stdout + proc.stderr

    def test_old_records_stay_in_default_new_projects_are_isolated(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("""CREATE TABLE sessions(id TEXT PRIMARY KEY, topic TEXT, parent TEXT, state TEXT,
                       plan TEXT DEFAULT '', workspace TEXT DEFAULT '', started REAL, owner INTEGER)""")
            db.execute("INSERT INTO sessions(id,topic,state) VALUES('old','已有的议题','consensus')")
        self.assertIn("已有的议题", self.cli("list"))
        path = self.home / "Project With Spaces"
        self.cli("project", "add", "研究 A", str(path))
        self.assertTrue(path.is_dir())
        self.assertNotIn("已有的议题", self.cli("list"))
        self.cli("show", "old", ok=False)
        self.cli("ask", "codex", "跟进", "--after", "old", ok=False)
        self.cli("implement", "old", ok=False)
        self.assertIn("已有的议题", self.cli("--project", "默认", "show", "old"))
        self.assertIn("研究 A", self.cli("project", "list"))

    @unittest.skipIf(os.name == "nt", "POSIX executable fixture")
    def test_number_menus_and_session_project_switch(self):
        target = self.home / "试验"
        self.cli("project", "add", "A", str(target))
        self.cli("project", "add", "B")
        agy = self.home / "agy"
        agy.write_text("#!/bin/sh\nprintf 'gemini-a\tModel A\ngemini-b\tModel B\nclaude-test\tClaude\n'\n")
        agy.chmod(0o755)
        self.env["ROUNDTABLE_AGY_BIN"] = str(agy)
        output = self.cli("chat", stdin="/project\n1\n/model gemini\n2\n/quit\n")
        self.assertIn("已保存  A · gemini · gemini-b", output)
        self.assertIn("gemini-b", self.cli("model"))
        self.assertNotIn("gemini-b", self.cli("--project", "B", "model"))

    @unittest.skipIf(os.name == "nt", "POSIX executable fixture")
    def test_selection_reaches_worker_and_execute_uses_project_folder(self):
        exe = self.home / "codex"
        exe.write_text("#!" + sys.executable + "\n" + """
import json, os, sys
from pathlib import Path
p = Path(os.environ['TEST_RECEIPT'])
args = sys.argv[1:]
p.write_text(args[args.index('--model')+1] + '\\n' + os.getcwd())
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':json.dumps({'status':'done','report':'ok'}) if '--output-schema' in args else 'ok'}}))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':10,'output_tokens':1}}))
""")
        exe.chmod(0o755)
        receipt = self.home / "receipt"
        self.env.update(ROUNDTABLE_CODEX_BIN=str(exe), TEST_RECEIPT=str(receipt))
        target = self.home / "Research"
        self.cli("project", "add", "研究", str(target))
        self.cli("model", "set", "codex", "gpt-test")
        self.cli("ask", "codex", "题目")
        self.assertEqual(receipt.read_text().splitlines()[0], "gpt-test")
        with closing(sqlite3.connect(self.db)) as db, db:
            sid, = db.execute("SELECT id FROM sessions").fetchone()
            db.execute("UPDATE sessions SET state='consensus', plan='演示方案' WHERE id=?", (sid,))
        self.cli("implement", sid)
        self.assertEqual(receipt.read_text().splitlines(), ["gpt-test", str(target.resolve())])
        self.assertIn("gpt-test", self.cli("show", sid))
        self.assertNotIn("gpt-test", self.cli("--project", "默认", "model"))
        self.cli("model", "set", "codex", "default")
        self.assertNotIn("gpt-test", self.cli("model"))
