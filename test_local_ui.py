"""API boundary checks without binding network sockets or invoking model CLIs."""
import io
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import patch

from local_ui import Handler, choose_directory


class Request:
    def __init__(self, message):
        self.message = io.BytesIO(message)
        self.reply = bytearray()

    def makefile(self, mode, size):
        return self.message

    def sendall(self, data):
        self.reply.extend(data)


class BrowserAPITests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env = patch.dict(os.environ, ROUNDTABLE_HOME=temp.name)
        env.start()
        self.addCleanup(env.stop)

    def request(self, path, *, body=None, host="127.0.0.1:8765", origin=None, key="test"):
        data = json.dumps(body).encode() if body is not None else b""
        method = "POST" if body is not None else "GET"
        headers = [f"{method} {path} HTTP/1.0", f"Host: {host}", f"X-Roundtable: {key}",
                   "Content-Type: application/json", f"Content-Length: {len(data)}"]
        if origin:
            headers.append("Origin: " + origin)
        req = Request(("\r\n".join(headers) + "\r\n\r\n").encode() + data)
        Handler(req, ("127.0.0.1", 1234), SimpleNamespace(server_port=8765, key="test"))
        head, raw = bytes(req.reply).split(b"\r\n\r\n", 1)
        return int(head.split()[1]), raw

    def test_only_local_page_can_access_history_or_change_settings(self):
        code, html = self.request("/")
        self.assertEqual(code, 200)
        self.assertIn(b'name="roundtable-key" content="test"', html)
        self.assertEqual(self.request("/api/state", key="wrong")[0], 403)
        self.assertEqual(self.request("/", host="other.example:8765")[0], 403)
        self.assertEqual(self.request("/api/project", body={"action": "add", "name": "bad"},
                                      origin="https://other.example")[0], 403)
        self.assertEqual(json.loads(self.request("/api/state")[1])["projects"], ["默认"])

    def test_ui_project_model_settings_are_scoped_and_persistent(self):
        self.assertEqual(self.request("/api/project", body={"action": "add", "name": "A"})[0], 200)
        self.assertEqual(self.request("/api/model", body={"project": "A", "agent": "gemini",
                                                          "model": "gemini-test-high"})[0], 200)
        a = json.loads(self.request("/api/state?project=A")[1])
        self.assertEqual(a["seats"][1]["model"], "gemini-test-high")
        self.assertEqual(a["sessions"], [])
        self.assertEqual(self.request("/api/state?project=A&session=missing")[0], 400)

    def test_browse_existing_directories_and_store_valid_effort(self):
        folder = Path(os.environ["ROUNDTABLE_HOME"])
        (folder / "已存在的目录").mkdir()
        (folder / "普通文件").touch()
        code, raw = self.request("/api/directories?"+urlencode({"path":str(folder)}))
        self.assertEqual((code,json.loads(raw)["folders"]),(200,["已存在的目录"]))
        with patch("projects.model_options",return_value={"gpt-test":["low","high"]}):
            payload = {"agent":"codex","model":"gpt-test","effort":"high"}
            self.assertEqual(self.request("/api/model",body=payload)[0],200)
            self.assertEqual(self.request("/api/model",body={**payload,"effort":"unknown"})[0],400)
        state = json.loads(self.request("/api/state")[1])
        self.assertEqual((state["seats"][0]["model"],state["seats"][0]["effort"]),("gpt-test","high"))
        self.assertEqual(self.request("/api/trash",body={"action":"remove"})[0],404)

    def test_claude_opt_in_and_single_seat_routing(self):
        with patch("local_ui.account_quota") as quota:
            self.assertEqual(self.request("/api/quota?agent=claude")[0],400)
            quota.assert_not_called()
        model = {"agent":"claude","model":"claude-opus-5-5","effort":"max"}
        self.assertEqual(self.request("/api/model",body=model)[0],200)
        with patch("projects.check_claude",side_effect=ValueError("IP")):
            self.assertEqual(self.request("/api/claude",body={"enabled":"on"})[0],400)
        self.assertEqual(self.request("/api/start",body={"mode":"claude","topic":"test"})[0],400)
        with patch("projects.check_claude"):
            self.assertEqual(self.request("/api/claude",body={"enabled":"on"})[0],200)
        seats = json.loads(self.request("/api/state")[1])["seats"]
        self.assertEqual(seats[-1]["effort"], "max")
        with patch("local_ui.start_worker") as worker:
            self.assertEqual(self.request("/api/start",body={"mode":"claude","topic":"test"})[0],200)
            self.assertEqual(worker.call_args.args[-3],"claude")

    def test_quota_refresh_does_not_start_a_discussion(self):
        with patch("local_ui.account_quota", return_value={"windows": [], "checked": 1}) as quota, \
             patch("local_ui.start_worker") as worker:
            self.assertEqual(self.request("/api/quota?agent=gemini&refresh=1")[0], 200)
            quota.assert_called_once_with("gemini", True, None)
            self.assertEqual(self.request("/api/start", body={"mode":"probe"})[0], 400)
            worker.assert_not_called()
        self.assertEqual(json.loads(self.request("/api/state")[1])["sessions"], [])

    def test_runtime_preferences_and_round_cap_are_project_scoped(self):
        with patch.dict(os.environ, ROUNDTABLE_TIMEOUT="1200"):
            default = json.loads(self.request("/api/state")[1])
        self.assertEqual((default["default_timeout_seconds"],default["plan_versions"]), (1200,2))
        prefs = {"tool_mode":"auto", "minutes":"24", "plan_versions":"3"}
        self.assertEqual(self.request("/api/preferences", body=prefs)[0], 200)
        self.assertEqual(self.request("/api/preferences", body={**prefs,"plan_versions":"4"})[0], 400)
        current = json.loads(self.request("/api/state")[1])
        self.assertEqual((current["tool_mode"],current["call_minutes"],current["plan_versions"]), ("auto",24,3))
        with patch("local_ui.start_worker") as worker:
            code, raw = self.request("/api/start", body={"topic":"round limit","mode":"both"})
        self.assertEqual(code,200)
        self.assertIsNone(worker.call_args.args[-2])
        record = json.loads(self.request("/api/state?session="+json.loads(raw)["session"])[1])["selected"]
        self.assertEqual(record["plan_versions"],3)

    def test_native_picker_handles_selected_cancelled_and_headless(self):
        path = Path(os.environ["ROUNDTABLE_HOME"]) / "中文 ' 工作区"
        path.mkdir()
        with patch("local_ui.sys.platform", "darwin"), patch("local_ui.subprocess.run") as run:
            run.return_value = SimpleNamespace(returncode=0, stdout=str(path)+"/\n", stderr="")
            code, raw = self.request("/api/choose-directory", body={"path":str(path)})
            self.assertEqual((code,json.loads(raw)), (200,{"status":"selected","path":str(path.resolve())}))
            self.assertEqual(run.call_args.args[0][-1], str(path.resolve()))
            self.assertNotIn(str(path),run.call_args.args[0][-2])
            run.return_value = SimpleNamespace(returncode=0, stdout="\n", stderr="")
            self.assertEqual(choose_directory(str(path)), {"status":"cancelled"})
        with patch("local_ui.sys.platform", "win32"), patch("local_ui.subprocess.run") as run:
            run.return_value = SimpleNamespace(returncode=0, stdout=str(path)+"\n", stderr="")
            self.assertEqual(choose_directory(str(path)), {"status":"selected","path":str(path.resolve())})
            self.assertIn("askdirectory",run.call_args.args[0][-2])
        with patch("local_ui.sys.platform", "linux"), patch.dict(os.environ, DISPLAY="", WAYLAND_DISPLAY=""), \
             patch("local_ui.subprocess.run") as run:
            self.assertEqual(choose_directory(None), {"status":"unavailable"})
            run.assert_not_called()
