"""Local browser workspace for the existing CLI engine."""
import asyncio
import errno
import json
import os
import secrets
import sqlite3
import threading
import time
import webbrowser
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import roundtable as rt
from quotas import read_quota
from projects import DEFAULT, move_trash, model_command, models_for, project_command, project_row, workspace
from providers import AGENTS, binary, catalog

ASSETS = Path(__file__).resolve().parent / "ui"
FILES = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
         "/style.css": ("style.css", "text/css")}


def state(db, project, sid=None):
    row = project_row(db, project)
    project = row["name"]
    models = models_for(row)
    seats = []
    for name in AGENTS:
        calls = db.execute("""SELECT c.model,c.ended,c.error,c.usage FROM calls c
                            JOIN sessions s ON s.id=c.session WHERE s.project=? AND c.agent=?
                            ORDER BY c.id DESC""", (project, name))
        status, total, missing, matched = "待验证", 0, 0, False
        for call in calls:
            if not matched and call["model"] == models[name]:
                status = "运行中" if call["ended"] is None else "最近失败" if call["error"] else "最近连通"
                matched = True
            if call["ended"] is not None:
                n = json.loads(call["usage"] or "{}").get("total")
                if n is None:
                    missing += 1
                else:
                    total += n
        seats.append(dict(agent=name, model=models[name], status=status if binary(name) else "缺少 CLI",
                          tokens=total, unknown=missing))
    sessions = [dict(r) for r in db.execute("""SELECT id,substr(topic,1,90) AS topic,state,started
                   FROM sessions WHERE project=? AND trash_root IS NULL ORDER BY started DESC LIMIT 50""", (project,))]
    selected = None
    if sid:
        record = rt.session(db, sid, project)
        selected = {k: record[k] for k in ("id", "topic", "parent", "state", "plan", "workspace", "started", "stop_requested")}
        selected["calls"] = [dict(c) for c in db.execute("""SELECT stage,agent,model,reply,error,usage,ended,started
                                                FROM calls WHERE session=? ORDER BY id""", (sid,))]
    running = [dict(r) for r in db.execute("""SELECT id,project,substr(topic,1,70) AS topic,state,stop_requested
                   FROM sessions WHERE state IN ('active','implementing') ORDER BY started DESC""")]
    return dict(project=project, running=running, path=str(workspace(row) or ""), projects=[r[0] for r in db.execute(
        "SELECT name FROM projects WHERE trashed=0 ORDER BY name")], seats=seats, sessions=sessions, selected=selected)


quota_cache = {}
quota_locks = {agent: threading.Lock() for agent in AGENTS}


def account_quota(agent, force=False):
    if agent not in AGENTS:
        raise ValueError("未知席位")
    with quota_locks[agent]:
        saved = quota_cache.get(agent)
        if saved and not force and time.time() - saved["checked"] < 60:
            return saved
        try:
            result = read_quota(agent)
        except (OSError, ValueError, asyncio.TimeoutError) as exc:
            if saved:
                return {**saved, "stale": True, "error": str(exc)}
            raise
        quota_cache[agent] = result
        return result


def start_worker(target, *args):
    def work():
        with closing(rt.database()) as db:
            asyncio.run(target(db, *args))
    threading.Thread(target=work, daemon=False).start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, data, mime="application/json"):
        payload = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; object-src 'none'; "
                         "base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self.dispatch(False)

    def do_POST(self):
        self.dispatch(True)

    def dispatch(self, post):
        host = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != host or self.headers.get("Origin", "http://" + host) != "http://" + host:
            return self.send(403, {"error": "请从本机圆桌地址打开"})
        url = urlsplit(self.path)
        try:
            if not post and url.path in FILES:
                filename, mime = FILES[url.path]
                raw = (ASSETS / filename).read_bytes()
                if url.path == "/":
                    raw = raw.replace(b"__LOCAL_KEY__", self.server.key.encode())
                return self.send(200, raw, mime)
            if not secrets.compare_digest(self.headers.get("X-Roundtable", ""), self.server.key):
                return self.send(403, {"error": "请刷新圆桌页面"})
            if post:
                size = int(self.headers.get("Content-Length", 0))
                if self.headers.get_content_type() != "application/json" or not 0 < size <= 1048576:
                    raise ValueError("请求格式无效或内容过长")
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict) or any(not isinstance(v, str) for v in body.values()):
                    raise ValueError("参数格式无效")
            else:
                body = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path == "/api/quota" and not post:
                return self.send(200, account_quota(body.get("agent"), body.get("refresh") == "1"))
            if url.path == "/api/catalog" and not post:
                agent = body.get("agent")
                if agent not in AGENTS:
                    raise ValueError("请选择 Codex 或 Gemini")
                return self.send(200, {"models": catalog(agent)})
            with closing(rt.database()) as db:
                project = project_row(db, body.get("project"))["name"]
                sid = body.get("session") or None
                if not post and url.path == "/api/state":
                    result = state(db, project, sid)
                elif post and url.path == "/api/stop":
                    rt.request_stop(db, sid, project)
                    result = {"ok":True}
                elif url.path == "/api/trash":
                    if post:
                        action = body["action"]
                        if action not in ("remove","restore"):
                            raise ValueError("未知回收站操作")
                        move_trash(db, project, body["kind"], body["item"], action == "restore")
                        result = {"project": DEFAULT if action=="remove" and body["kind"]=="project" else project}
                    else:
                        result = {"projects":[r[0] for r in db.execute("SELECT name FROM projects WHERE trashed=1 ORDER BY name")],
                                  "sessions":[dict(r) for r in db.execute("""SELECT id,substr(topic,1,90) AS topic FROM sessions
                                          WHERE project=? AND id=trash_root ORDER BY started DESC""", (project,))]}
                elif post and url.path == "/api/project":
                    action = body["action"]
                    if action == "add":
                        args = ["add", body["name"]] + ([body["path"]] if body.get("path") else [])
                    elif action == "use":
                        args = ["use", body["name"]]
                    elif action == "path":
                        args = ["path", body["path"]]
                    else:
                        raise ValueError("未知项目操作")
                    result = {"project": project_command(db, project, args)}
                elif post and url.path == "/api/model":
                    model_command(db, project, ["set", body["agent"], body["model"]])
                    result = {"ok": True}
                elif post and url.path == "/api/start":
                    mode = body.get("mode", "both")
                    if mode not in (*AGENTS, "both", "probe"):
                        raise ValueError("未知讨论模式")
                    topic = "连接测试" if mode == "probe" else body["topic"].strip()
                    sid, context, models = rt.prepare_topic(db, topic, sid, project)
                    start_worker(rt.run_topic, sid, context, models, mode if mode in AGENTS else None, 2, mode == "probe")
                    result = {"session": sid}
                elif post and url.path == "/api/implement":
                    # The engine claims the approved plan atomically. Its running state is visible to polling tabs.
                    outcome = asyncio.run(rt.implement(db, sid, body.get("path"), project))
                    result = {"state": outcome}
                else:
                    return self.send(404, {"error": "找不到此页面"})
            self.send(200, result)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
            self.send(400, {"error": str(exc)})


def serve(port, open_browser, project=None, sid=None):
    old = os.umask(0o077)
    try:
        with closing(rt.database()) as db:
            current = project_row(db, project)["name"]
            if sid:
                rt.session(db, sid, current)
    finally:
        os.umask(old)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = False
    server.key = secrets.token_urlsafe(32)
    query = {k: v for k, v in (("project", project), ("session", sid)) if v}
    url = f"http://127.0.0.1:{server.server_port}/" + ("?" + urlencode(query) if query else "")
    print(f"科研圆桌  {url}\n保持此终端打开。按 Ctrl+C 结束本地服务。", flush=True)
    if open_browser:
        webbrowser.open(url)
    with server:
        server.serve_forever()
