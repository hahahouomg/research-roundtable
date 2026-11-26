import asyncio
import json
import os
from pathlib import Path
from record_store import discussion_folder
import tempfile
import unittest
from unittest.mock import patch

import reports
import roundtable as rt


class ReportTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "POSIX executable fixture")
    def test_export_requires_complete_draft_and_reuses_rendered_file(self):
        html = "<html><head></head><body><h1>研究方案</h1></body></html>"
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,ROUNDTABLE_HOME=tmp):
            db = rt.database()
            self.addCleanup(db.close)
            db.execute("INSERT INTO sessions(id,topic,state,settings) VALUES('demo','题目','disputed',?)",
                       (json.dumps({"models":{"gemini":"gemini-test"}}),))
            with self.assertRaisesRegex(ValueError,"共识"):
                asyncio.run(reports.export_pdf(db,"demo","默认"))
            db.execute("UPDATE sessions SET state='consensus', plan='已通过'")
            discussion_folder("默认", "demo").mkdir(parents=True)
            with self.assertRaisesRegex(ValueError,"最终方案撰写"):
                asyncio.run(reports.export_pdf(db,"demo","默认"))
            db.execute("INSERT INTO calls(session,stage,agent,reply,ended) VALUES('demo','最终方案撰写','gemini','Gemini 定稿',1)")
            browser = Path(tmp)/"print"
            browser.write_text('#!/bin/sh\nfor arg do case "$arg" in --print-to-pdf=*) printf "%%PDF-1.7" > "${arg#*=}" ;; esac; done\n')
            browser.chmod(0o700)
            with patch("reports.chrome", return_value=str(browser)), patch("reports.rt.call",return_value=html) as writer:
                path = asyncio.run(reports.export_pdf(db,"demo","默认"))
                self.assertEqual(path.read_bytes(),b"%PDF-1.7")
                self.assertEqual((path.parent / "排版源稿.html.txt").read_text(encoding="utf-8"),html)
                asyncio.run(reports.export_pdf(db,"demo","默认"))
                writer.assert_awaited_once()
                self.assertEqual(writer.await_args.args[3], "gemini")

    def test_active_content_is_rejected_before_printing(self):
        with self.assertRaises(ValueError):
            reports.print_source("<html><head></head><body><script>alert(1)</script></body></html>")
