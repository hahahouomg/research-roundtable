"""Local browser workspace for the existing CLI engine."""
import asyncio
import errno
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import roundtable as rt
from quotas import read_quota
from reports import export_pdf, pdf_path
from local_settings import claude_ip
from record_store import discussion_folder, project_folder
from runtime import show_folder
from projects import claude_access, configure_claude_ip, model_command, models_for, project_command, project_row, workspace
from implementation_preview import PATCH_NAME
from outcomes import failure_kind
from providers import MODEL_SEATS, binary, default_timeout, model_options

ASSETS = Path(__file__).resolve().parent / "ui"
FILES = {"/visual.js": ("visual.js", "text/javascript"), "/visual.css": ("visual.css", "text/css"),
         "/discussion.js": ("discussion.js", "text/javascript"), "/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
         "/style.css": ("style.css", "text/css"), "/i18n.js": ("i18n.js", "text/javascript")}


def state(db, project, sid=None):
    row = project_row(db, project)
    project = row["name"]
    models = models_for(row)
    seats = []
    for name in models:
        effort = row[name + "_effort"] if name in ("codex", "claude") else None
        calls = db.execute("""SELECT c.model,c.effort,c.ended,c.error,c.usage FROM calls c
                            JOIN sessions s ON s.id=c.session WHERE s.project=? AND c.agent=?
                            ORDER BY c.id DESC""", (project, name))
        status, total, missing, matched = "待验证", 0, 0, False
        for call in calls:
            if not matched and call["model"] == models[name] and call["effort"] == effort:
                status = "运行中" if call["ended"] is None else "最近失败" if call["error"] else "最近连通"
                matched = True
            if call["ended"] is not None:
                n = json.loads(call["usage"] or "{}").get("total")
                if n is None:
                    missing += 1
                else:
                    total += n
        seats.append(dict(agent=name, model=models[name], status=status if binary(name) else "缺少 CLI",
                          tokens=total, unknown=missing, effort=effort))
    sessions = [dict(r) for r in db.execute("""SELECT id,substr(topic,1,90) AS topic,state,started
                   FROM sessions WHERE project=? AND trash_root IS NULL ORDER BY started DESC LIMIT 50""", (project,))]
    selected = None
    if sid:
        record = rt.session(db, sid, project)
        selected = {k: record[k] for k in ("id", "topic", "parent", "state", "plan", "workspace", "started", "stop_requested", "failure")}
        settings = json.loads(record["settings"] or "{}")
        selected["seat_names"] = list(settings.get("models") or {}) if settings.get("mode", "both") == "both" else []
        selected["notice"] = settings.get("notice")
        selected["input_change"] = settings.get("input_change")
        selected["implementation_preview"] = bool(settings.get("implementation_preview"))
        selected["has_patch"] = (discussion_folder(project, sid) / PATCH_NAME).is_file()
        selected["moderator"] = rt.moderator_for(db, sid, settings["models"]) if "models" in settings and settings.get("mode", "both") == "both" else None
        selected["can_resume"] = record["state"] == "incomplete" and settings.get("mode") in ("both", *settings.get("models", {}))
        selected["plan_versions"] = settings.get("plan_versions") if selected["moderator"] else None
        selected["folder"] = str(discussion_folder(project, sid))
        selected["has_pdf"] = pdf_path(record["id"], project).is_file()
        selected["calls"] = [dict(c, failure_kind=c["failure_kind"] or failure_kind(c["error"])) for c in db.execute("""
                             SELECT id,stage,agent,model,effort,reply,error,failure_kind,usage,ended,started
                             FROM calls WHERE session=? ORDER BY id""", (sid,))]
        selected["review"] = rt.discussion_review(db, sid, selected["calls"], settings)
        selected["permissions"] = [
            dict(id=p["id"], stage=p["stage"], agent=p["agent"], details=json.loads(p["details"]), can_allow=bool(p["can_allow"]))
            for p in db.execute("""SELECT p.*, c.stage, c.agent FROM tool_permissions p JOIN calls c ON c.id=p.call_id
                        WHERE c.session=? AND c.ended IS NULL AND p.decision='pending' ORDER BY p.id""", (sid,))]
    running = [dict(r) for r in db.execute("""SELECT s.id,s.project,substr(s.topic,1,70) AS topic,s.state,s.stop_requested,
                   EXISTS (SELECT 1 FROM tool_permissions p JOIN calls c ON p.call_id=c.id
                           WHERE c.session=s.id AND c.ended IS NULL AND p.decision='pending') AS awaiting
                   FROM sessions s WHERE s.trash_root IS NULL AND (s.state IN ('active','implementing','summarizing')
                   OR EXISTS (SELECT 1 FROM calls c WHERE c.session=s.id AND c.ended IS NULL)) ORDER BY s.started DESC""")]
    try:
        configured_timeout = default_timeout()
    except ValueError:
        configured_timeout = None
    return dict(project=project, tool_mode=row["tool_mode"], call_minutes=row["call_minutes"],
                plan_versions=row["plan_versions"], default_timeout_seconds=configured_timeout,
                claude_configured=bool(claude_ip()),
                native_folders=bool(os.name == "nt" or sys.platform == "darwin" or os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")),
                project_folder=str(project_folder(project)), running=running, path=str(workspace(row) or ""), projects=[r[0] for r in db.execute(
        "SELECT name FROM projects WHERE trashed=0 ORDER BY name")], seats=seats, sessions=sessions, selected=selected)


quota_cache = {}
quota_locks = {agent: threading.Lock() for agent in MODEL_SEATS}


def account_quota(agent, force=False, check_access=None):
    if agent not in MODEL_SEATS:
        raise ValueError("未知席位")
    with quota_locks[agent]:
        if check_access:
            check_access()
        saved = quota_cache.get(agent)
        if saved and not force and time.time() - saved["checked"] < 60:
            return {**saved, "cached": True}
        try:
            result = read_quota(agent, check_access=check_access)
        except (OSError, ValueError, asyncio.TimeoutError) as exc:
            if check_access:
                check_access()
            if saved:
                return {**saved, "stale": True, "error": str(exc)}
            raise
        quota_cache[agent] = result
        return result


def choose_directory(path):
    start = Path(path).expanduser() if path else Path.home()
    if not start.is_dir() and start.is_absolute():
        start = next((p for p in start.parents if p.is_dir()), Path.home())
    start = start.resolve() if start.is_dir() else Path.home()
    if sys.platform == "win32":
        script = ("import sys, tkinter as t; from tkinter import filedialog; "
                  "root=t.Tk(); root.withdraw(); root.attributes('-topmost', True); "
                  "print(filedialog.askdirectory(parent=root, initialdir=sys.argv[1], mustexist=True)); root.destroy()")
        args = [sys.executable, "-X", "utf8", "-c", script, str(start)]
    elif sys.platform == "darwin":
        script = """on run argv
            try
                activate
                set selectedFolder to choose folder with prompt "选择工作目录" default location (POSIX file (item 1 of argv) as alias)
                return POSIX path of selectedFolder
            on error number -128
                return ""
            end try
        end run"""
        args = ["/usr/bin/osascript", "-e", script, str(start)]
    elif sys.platform.startswith("linux") and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        if shutil.which("zenity"):
            args = ["zenity", "--file-selection", "--directory", "--title=选择工作目录", "--filename", os.path.join(str(start), "")]
        elif shutil.which("kdialog"):
            args = ["kdialog", "--title", "选择工作目录", "--getexistingdirectory", str(start)]
        else:
            return {"status": "unavailable"}
    else:
        return {"status": "unavailable"}
    try:
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
    except OSError:
        return {"status": "unavailable"}
    if result.returncode == 1 and sys.platform.startswith("linux") and "display" not in result.stderr.lower():
        return {"status": "cancelled"}
    if result.returncode:
        return {"status": "unavailable"}
    # Remove the dialog's line terminator, preserving spaces in real folder names.
    selected = result.stdout.removesuffix("\n")
    if not selected:
        return {"status": "cancelled"}
    chosen = Path(selected)
    if not chosen.is_absolute() or not chosen.is_dir():
        raise ValueError("所选目录已不存在，请重新选择")
    return {"status": "selected", "path": str(chosen.resolve())}


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
        self.send_header("Content-Type", mime if mime == "application/pdf" else mime + "; charset=utf-8")
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
            if url.path == "/api/catalog" and not post:
                agent = body.get("agent")
                if agent not in MODEL_SEATS:
                    raise ValueError("未知席位")
                options = model_options(agent)
                return self.send(200, {"models": list(options), "efforts": options})
            if url.path == "/api/directories" and not post:
                if body.get("path") == ":drives" and os.name == "nt":
                    drives = [str(Path(letter + ":/")) for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if Path(letter + ":/").is_dir()]
                    return self.send(200, {"path": ":drives", "parent": ":drives", "home": str(Path.home()), "folders": [], "drives": drives})
                directory = Path(body.get("path") or Path.home()).expanduser().resolve()
                children = sorted((p.name for p in directory.iterdir() if p.is_dir()), key=lambda name: (name.startswith("."), name.casefold()))
                return self.send(200, {"path": str(directory), "parent": ":drives" if os.name == "nt" and directory == directory.parent else str(directory.parent),
                                       "home": str(Path.home()), "folders": children, "separator": os.sep})
            if url.path == "/api/choose-directory" and post:
                return self.send(200, choose_directory(body.get("path")))
            with closing(rt.database()) as db:
                project = project_row(db, body.get("project"))["name"]
                sid = body.get("session") or None
                if not post and url.path == "/api/quota":
                    agent = body.get("agent")
                    if agent not in models_for(project_row(db, project)):
                        raise ValueError("项目未启用此席位")
                    result = account_quota(agent, body.get("refresh") == "1",
                                           claude_access(db, project) if agent == "claude" else None)
                elif not post and url.path == "/api/state":
                    result = state(db, project, sid)
                elif not post and url.path == "/api/record":
                    result = {"markdown": rt.transcript(db, sid, project)}
                elif not post and url.path == "/api/patch":
                    rt.session(db, sid, project)
                    path = discussion_folder(project, sid) / PATCH_NAME
                    if not path.is_file():
                        raise ValueError("实施预览没有可下载的补丁")
                    if body.get("excerpt") == "1":
                        with path.open("rb") as stream:
                            data = stream.read(128 * 1024 + 1)
                        result = {"patch": data[:128 * 1024].decode("utf-8", "replace"), "truncated": len(data) > 128 * 1024}
                    else:
                        return self.send(200, path.read_bytes(), "application/octet-stream")
                elif url.path == "/api/pdf":
                    record = rt.session(db, sid, project)
                    path = pdf_path(record["id"], project)
                    if post:
                        asyncio.run(export_pdf(db, sid, project))
                        result = {"ok": True}
                    elif path.is_file():
                        return self.send(200, path.read_bytes(), "application/pdf")
                    else:
                        raise ValueError("图文 PDF 尚未生成")
                elif post and url.path == "/api/preferences":
                    saved = project_row(db, project)
                    tool_mode = body.get("tool_mode")
                    minutes = int(body.get("minutes") or 0)
                    versions = int(body.get("plan_versions", saved["plan_versions"]))
                    if tool_mode not in ("auto", "cli") or not 0 <= minutes <= 120:
                        raise ValueError("请选有效的工具策略，超时可留空或填写 1–120 分钟")
                    if versions not in (1, 2, 3):
                        raise ValueError("请选择 1–3 版候选方案")
                    db.execute("""UPDATE projects SET tool_mode=?,call_minutes=?,plan_versions=?
                                  WHERE name=?""", (tool_mode, minutes or None, versions, project))
                    result = {"ok": True}
                elif post and url.path == "/api/permission":
                    rt.decide_tool(db, sid, project, body["request"], body["decision"])
                    result = {"ok": True}
                elif post and url.path == "/api/stop":
                    rt.request_stop(db, sid, project)
                    result = {"ok":True}
                elif post and url.path == "/api/resume":
                    asyncio.run(rt.resume_discussion(db, sid, project))
                    result = {"session":sid}
                elif post and url.path == "/api/close-discussion":
                    asyncio.run(rt.close_discussion(db, sid, project))
                    result = {"session":sid}
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
                    args = ["set", body["agent"], body["model"]]
                    if body.get("effort"):
                        args.append(body["effort"])
                    model_command(db, project, args)
                    result = {"ok": True}
                elif post and url.path == "/api/folder":
                    if sid:
                        rt.session(db, sid, project)
                        path = discussion_folder(project, sid)
                    else:
                        path = project_folder(project)
                        path.mkdir(parents=True, exist_ok=True, mode=0o700)
                    show_folder(path)
                    result = {"ok": True}
                elif post and url.path == "/api/claude-config":
                    configure_claude_ip(db, body["ip"])
                    result = {"ok": True}
                elif post and url.path == "/api/claude":
                    model_command(db, project, ["claude", body["enabled"]])
                    result = {"ok": True}
                elif post and url.path == "/api/start":
                    mode = body.get("mode", "both")
                    if mode not in (*models_for(project_row(db, project)), "both"):
                        raise ValueError("未知讨论模式")
                    sid, context, models = rt.prepare_topic(db, body["topic"].strip(), sid, project, body.get("moderator", "") if mode == "both" else "", mode)
                    start_worker(rt.run_topic, sid, context, models, None if mode == "both" else mode, None, False)
                    result = {"session": sid}
                elif post and url.path == "/api/implement":
                    # The engine claims the approved plan atomically. Its running state is visible to polling tabs.
                    mode = body.get("mode", "preview")
                    if mode not in ("preview", "direct"):
                        raise ValueError("未知实施模式")
                    outcome = asyncio.run(rt.implement(db, sid, body.get("path"), project, preview=mode == "preview"))
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
