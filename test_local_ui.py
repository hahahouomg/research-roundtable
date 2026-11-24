"""API boundary checks without binding network sockets or invoking model CLIs."""
import io
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from local_ui import Handler


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
