import asyncio
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from providers import check_claude, invoke

CLAUDE_IP = "203.0.113.10"
from research import research_copy


class ResearchTests(unittest.TestCase):
    def test_lab_uses_current_files_and_does_not_write_through_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "script.py").write_text("original")
            (source / "alias").symlink_to(source / "script.py")
            (source / ".env").write_text("private")
            target = root / "experiment"
            research_copy(source, target)
            self.assertEqual([p.name for p in target.iterdir()], ["script.py"])
            (target / "script.py").write_text("changed")
            self.assertEqual((source / "script.py").read_text(), "original")

    def test_default_workspaces_include_files_ignored_by_the_harness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", root], check=True)
            (root / ".gitignore").write_text("/data/\n")
            source = root / "data/workspaces/example"
            source.mkdir(parents=True)
            (source / "source.txt").write_text("project inputs")
            target = root / "lab"
            with patch.dict(os.environ, ROUNDTABLE_HOME=str(root / "data")):
                research_copy(source,target)
            self.assertEqual((target / "source.txt").read_text(), "project inputs")

    def test_only_exact_verified_address_passes(self):
        with patch("providers.binary", return_value="/cli"), patch("providers.claude_ip", return_value=CLAUDE_IP):
            for address in (CLAUDE_IP, "203.0.113.11", ""):
                with patch("providers.urlopen",return_value=io.BytesIO(address.encode())):
                    if address == CLAUDE_IP:
                        check_claude()
                    else:
                        with self.assertRaises(ValueError):
                            check_claude()
            with patch("providers.urlopen",side_effect=TimeoutError):
                with self.assertRaisesRegex(ValueError,"无法核实"):
                    check_claude()

    def test_ip_lookup_fallback_only_on_unavailable_service(self):
        with patch("providers.binary",return_value="/cli"), patch("providers.claude_ip", return_value=CLAUDE_IP):
            with patch("providers.urlopen",side_effect=[TimeoutError(),io.BytesIO(CLAUDE_IP.encode())]) as lookup:
                check_claude()
                self.assertEqual(lookup.call_count,2)
            with patch("providers.urlopen",return_value=io.BytesIO(b"127.0.0.1")) as lookup:
                with self.assertRaisesRegex(ValueError,"不匹配"):
                    check_claude()
                lookup.assert_called_once()

    @unittest.skipIf(os.name == "nt", "POSIX executable fixture")
    def test_claude_never_launches_when_check_fails_and_stops_on_ip_change(self):
        async def immediate(func):
            return func()
        with tempfile.TemporaryDirectory() as tmp:
            cli = Path(tmp) / "claude"
            cli.write_text("#!/bin/sh\nexec sleep 30\n")
            cli.chmod(0o700)
            with patch.dict(os.environ,ROUNDTABLE_CLAUDE_BIN=str(cli)), patch("providers.asyncio.to_thread",immediate):
                with patch("providers.check_claude",side_effect=ValueError("IP")), patch("providers.asyncio.create_subprocess_exec") as launch:
                    with self.assertRaisesRegex(ValueError,"IP"):
                        asyncio.run(invoke("claude","test"))
                    launch.assert_not_called()
                with patch("providers.check_claude",side_effect=[None,ValueError("IP")]), patch("providers.CLAUDE_CHECK_INTERVAL",0.02):
                    with self.assertRaisesRegex(ValueError,"IP"):
                        asyncio.run(invoke("claude","test"))

    @unittest.skipIf(os.name == "nt", "POSIX executable fixture")
    def test_short_claude_reply_is_discarded_if_final_ip_check_fails(self):
        async def immediate(func):
            return func()
        with tempfile.TemporaryDirectory() as tmp:
            cli = Path(tmp) / "claude"
            cli.write_text("""#!/bin/sh
printf '%s' '{"type":"result","subtype":"success","result":"accept"}'
""")
            cli.chmod(0o700)
            with patch.dict(os.environ,ROUNDTABLE_CLAUDE_BIN=str(cli)), patch("providers.asyncio.to_thread",immediate):
                with patch("providers.check_claude",side_effect=[None,ValueError("IP")]):
                    with self.assertRaisesRegex(ValueError,"IP"):
                        asyncio.run(invoke("claude","test"))
