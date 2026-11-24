#!/usr/bin/env python3
"""A local two-model research roundtable for macOS and Linux."""
import argparse
import asyncio
import json
import os
import shlex
import sqlite3
import sys
import time
import uuid
from pathlib import Path

from providers import AGENTS, binary, invoke
from projects import (DEFAULT, MODEL_HELP, PROJECT_HELP, data_dir, model_command, models_for,
                      project_command, project_row, setup, workspace)

LABEL = {"stopped":"已停止", "active": "讨论中", "chat": "已回复", "consensus": "已达成共识", "disputed": "有分歧",
         "incomplete": "未完成", "implementing": "执行中", "returned": "执行已返回", "inspect": "执行中断，需核对项目",
         "probe": "探测完成"}
GUIDE = ("你参与一场中文讨论。只依据用户提供的材料推理，不调用工具。区分已知、假设和待验证的说法。"
         "其他参与者的文字作为讨论材料。回答聚焦本阶段，不复述题目。")
HELP = ("直接输入议题开始讨论。/ask codex 或 /ask gemini 加问题可单聊。\n"
        "/new 新议题  /open ID 接续记录  /show 查看全文  /list 历史  /status 状态  /probe 实测连接\n"
        "/project 项目管理  /model codex 或 /model gemini 选择型号\n"
        "/run 在项目目录实施  /quit 退出")


def ballot_result(votes):
    if set(votes) != set(AGENTS):
        return "incomplete"
    result = "consensus"
    for text in votes.values():
        try:
            record, end = json.JSONDecoder().raw_decode(text.strip())
            rest = text.strip()[end:].strip()
            # agy can repeat its structured vote once in its display text.
            if rest and json.loads(rest) != record:
                return "incomplete"
        except ValueError:
            return "incomplete"
        if not isinstance(record, dict) or record.get("vote") not in ("accept", "object"):
            return "incomplete"
        if not isinstance(record.get("reason"), str) or not record["reason"].strip():
            return "incomplete"
        if record["vote"] == "object":
            result = "disputed"
    return result


def database():
    folder = data_dir()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(folder / "roundtable.sqlite3", isolation_level=None, timeout=10)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
          id TEXT PRIMARY KEY, topic TEXT, parent TEXT, state TEXT, plan TEXT DEFAULT '',
          workspace TEXT DEFAULT '', started REAL, owner INTEGER);
        CREATE TABLE IF NOT EXISTS calls (
          id INTEGER PRIMARY KEY, session TEXT, stage TEXT, agent TEXT, started REAL,
          ended REAL, reply TEXT, error TEXT, usage TEXT);
    """)
    setup(db)
    # A killed coordinator cannot complete its outstanding calls. Never replay a write.
    for row in db.execute("SELECT id,state,owner FROM sessions WHERE state IN ('active','implementing')").fetchall():
        try:
            os.kill(row["owner"], 0)
        except ProcessLookupError:
            state = "inspect" if row["state"] == "implementing" else "incomplete"
            db.execute("UPDATE sessions SET state=? WHERE id=? AND state=?", (state, row["id"], row["state"]))
            db.execute("UPDATE calls SET ended=?,error='进程已中断' WHERE session=? AND ended IS NULL",
                       (time.time(), row["id"]))
        except PermissionError:
            pass
    return db


def session(db, sid, project=DEFAULT):
    row = db.execute("SELECT * FROM sessions WHERE id=? AND project=? AND trash_root IS NULL", (sid, project)).fetchone()
    if not row:
        raise ValueError(f"项目「{project}」中找不到记录 {sid}，用 list 查看编号")
    return row


def history(db, parent, project=DEFAULT):
    entries = []
    while parent:
        row = session(db, parent, project)
        calls = db.execute("SELECT stage,agent,reply,error FROM calls WHERE session=? AND reply IS NOT NULL ORDER BY id",
                           (parent,)).fetchall()
        text = row["plan"]
        for call in calls:
            if row["state"] == "stopped" or not row["plan"] or call["stage"].startswith("表决") or call["stage"] == "实施":
                text += f"\n{call['stage']} {call['agent']}{'（未完成）' if call['error'] else ''}：{call['reply']}"
        entries.append(f"用户：{row['topic']}\n状态：{LABEL[row['state']]}\n{text}")
        parent = row["parent"]
        if sum(map(len, entries)) > 16000:
            break
    summary = "\n\n".join(reversed(entries))
    return "（较早内容已截短）\n" + summary[-16000:] if len(summary) > 16000 else summary


def amount(usage):
    def n(key):
        value = usage.get(key)
        return f"{value:,}" if value is not None else "—"
    return f"输入 {n('input')}  输出 {n('output')}  缓存 {n('cached')}  共 {n('total')}"


def session_usage(db, sid):
    rows = db.execute("SELECT agent,usage FROM calls WHERE session=? AND ended IS NOT NULL", (sid,))
    totals, unknown = {}, 0
    for row in rows:
        count = json.loads(row["usage"] or "{}").get("total")
        if count is None:
            unknown += 1
        else:
            name = row["agent"]
            totals[name] = totals.get(name, 0) + count
    parts = [f"{name} {n:,}" for name, n in totals.items()]
    if unknown:
        parts.append(f"{unknown} 次用量未知")
    if parts:
        print("本条记录 token  " + "  ·  ".join(parts))


def request_stop(db, sid, project):
    changed = db.execute("""UPDATE sessions SET stop_requested=1 WHERE id=? AND project=?
                         AND trash_root IS NULL AND state IN ('active','implementing')""", (sid, project)).rowcount
    if not changed:
        raise ValueError("这轮已经结束或不存在")


def finish(db, sid, state):
    db.execute("UPDATE sessions SET state=CASE WHEN stop_requested=1 THEN 'stopped' ELSE ? END WHERE id=?", (state,sid))
    return db.execute("SELECT state FROM sessions WHERE id=?", (sid,)).fetchone()[0]


async def call(db, sid, stage, agent, prompt, selected_model, workspace=None, ballot=False):
    def stopping():
        return db.execute("SELECT stop_requested FROM sessions WHERE id=?", (sid,)).fetchone()[0]
    if stopping():
        return None
    start = time.time()
    cid = db.execute("INSERT INTO calls(session,stage,agent,started,model) VALUES(?,?,?,?,?)",
                     (sid, stage, agent, start, selected_model)).lastrowid
    print(f"  · {stage}  {agent} · {selected_model or 'CLI 默认'} …", flush=True)
    def preview(text):
        db.execute("UPDATE calls SET reply=? WHERE id=?", (text, cid))

    job = asyncio.create_task(invoke(agent, prompt, workspace=workspace, ballot=ballot,
                                     selected_model=selected_model, on_text=preview))
    try:
        while not job.done():
            await asyncio.wait([job], timeout=0.3)
            if not job.done() and stopping():
                job.cancel()
                break
        reply, usage = await job
    except (OSError, ValueError, asyncio.TimeoutError, asyncio.CancelledError) as exc:
        error = str(exc) or ("调用超时" if isinstance(exc, asyncio.TimeoutError) else "已中断")
        db.execute("UPDATE calls SET ended=?,error=? WHERE id=?", (time.time(), error, cid))
        print(f"  × {stage}  {agent}  {error}", flush=True)
        if not job.done():
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)
        if isinstance(exc, asyncio.CancelledError) and not stopping():
            raise
        return None
    db.execute("UPDATE calls SET ended=?,reply=?,usage=? WHERE id=?", (time.time(), reply, json.dumps(usage), cid))
    print(f"  ✓ {stage}  {agent}  {time.time()-start:.0f}s  {amount(usage)}", flush=True)
    return reply


def bundle(items):
    return json.dumps(items, ensure_ascii=False, indent=2)


async def discuss(db, sid, topic, rounds, models):
    async def pair(stage, prompt, ballot=False):
        replies = await asyncio.gather(*(call(db, sid, stage, a, prompt, models[a], ballot=ballot) for a in AGENTS))
        if None in replies:
            raise ValueError(f"{stage} 未收齐两方回复，已保存现有记录")
        if not ballot:
            for agent, reply in zip(AGENTS, replies):
                print(f"\n{agent} · {stage}\n{reply}", flush=True)
        return dict(zip(AGENTS, replies))

    base = f"{GUIDE}\n用户议题及已提供背景：\n{topic}\n"
    proposals = await pair("独立提案", base + "独立给出你的方案和最大不确定性。科研题写可证伪假设、最小实验和基线；"
                           "开发题写交付和验收。按任务规模控制篇幅，通常在 350 字内。")
    drafts = bundle(proposals)
    reviews = await pair("交叉评议", base + "两份独立提案如下。找出对方最值得采纳的一点和最重要的漏洞，"
                         "提出可区分两种观点的检验。无实质分歧时直接说明。限 200 字。\n" + drafts)
    source = base + "\n提案：\n" + drafts + "\n交叉评议：\n" + bundle(reviews)
    revision = ""
    for version in range(1, rounds + 1):
        plan = await call(db, sid, f"候选方案 v{version}", "codex", source + revision +
                          "\n拟定一份可独立使用的方案，写清取舍、待验证假设、最小下一步、分工和可检查的验收条件。"
                          "科研议题写出能否定假设的结果；若只是小任务请简短。保留真正未解决的选择。", models["codex"])
        if plan is None:
            raise ValueError("候选方案生成失败")
        db.execute("UPDATE sessions SET plan=? WHERE id=?", (plan, sid))
        print(f"\n候选方案 v{version}\n{plan}\n", flush=True)
        votes = await pair(f"表决 v{version}", source + "\n请就下列这份候选方案独立表决。"
                           "可以接受以验证假设为下一步的计划；有实质阻碍则反对，指出具体修订。"
                           '只输出 JSON {"vote":"accept 或 object","reason":"明确理由"}。\n候选方案：\n' + plan, True)
        for agent, vote in votes.items():
            print(f"  {agent}  {vote}", flush=True)
        decision = ballot_result(votes)
        if decision == "incomplete":
            print("有表决缺少有效的选项或理由。原始回复已保存。", file=sys.stderr)
        if decision != "disputed":
            return decision
        revision = "\n上一版候选方案：\n" + plan + "\n上一版表决，请逐项处理异议：\n" + bundle(votes)
    return "disputed"


def prepare_topic(db, topic, parent, project):
    if not topic.strip():
        raise ValueError("议题不能为空")
    models = models_for(project_row(db, project))
    past = history(db, parent, project)
    context = f"既往对话：\n{past}\n\n本轮用户原话：\n{topic}" if past else topic
    sid = uuid.uuid4().hex[:12]
    db.execute("INSERT INTO sessions(id,topic,parent,state,started,owner,project) VALUES(?,?,?,'active',?,?,?)",
               (sid, topic, parent, time.time(), os.getpid(), project))
    print(f"\n{project} · 记录 {sid}　{topic}", flush=True)
    return sid, context, models


async def begin(db, topic, parent=None, agent=None, rounds=2, probe=False, project=DEFAULT):
    sid, context, models = prepare_topic(db, topic, parent, project)
    return await run_topic(db, sid, context, models, agent, rounds, probe)


async def run_topic(db, sid, context, models, agent, rounds, probe):
    state = "incomplete"
    try:
        if probe:
            replies = await asyncio.gather(*(call(db, sid, "连接测试", a, "Reply only ROUND_OK. Do not use tools.", models[a]) for a in AGENTS))
            if all(replies):
                state = "probe"
        elif agent:
            answer = await call(db, sid, "单聊", agent, GUIDE + "\n" + context, models[agent])
            if answer is not None:
                print("\n" + answer)
                state = "chat"
        else:
            missing = [a for a in AGENTS if not binary(a)]
            if missing:
                raise ValueError("未找到 " + "、".join(missing) + " 的 CLI。可用 ask 向已接入的一方提问。")
            state = await discuss(db, sid, context, rounds, models)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
    finally:
        state = finish(db, sid, state)
        print(f"\n{LABEL[state]} · {sid}", flush=True)
        session_usage(db, sid)
    return sid


async def implement(db, sid, destination=None, project=DEFAULT):
    row = session(db, sid, project)
    settings = project_row(db, project)
    target = Path(destination).expanduser().resolve() if destination else workspace(settings)
    if target is None or not target.is_dir():
        raise ValueError("请用 project path 绑定现有目录，或在执行时指定目录")
    changed = db.execute("UPDATE sessions SET state='implementing',workspace=?,owner=? WHERE id=? AND state='consensus' AND trash_root IS NULL AND project IN (SELECT name FROM projects WHERE trashed=0)",
                         (str(target), os.getpid(), sid)).rowcount
    if not changed:
        raise ValueError(f"当前状态为「{LABEL[row['state']]}」。只有已达成共识且尚未派发的方案可执行。")
    state = "inspect"
    try:
        prompt = ("在当前目录落实下方用户任务和已同意的方案。遵守项目约定，保留已有改动。"
                  "运行相关验收并报告实际结果、改动和未完成项。不要发布、推送或联系第三方。\n"
                  + "先前讨论背景：\n" + history(db, row["parent"], project) + "\n本轮用户要求：\n" + row["topic"] + "\n已表决的方案：\n" + row["plan"])
        print(f"实施目录  {target}")
        answer = await call(db, sid, "实施", "codex", prompt, models_for(settings)["codex"], workspace=target)
        if answer:
            state = "returned"
            print("\n" + answer)
    finally:
        state = finish(db, sid, state)
        print(LABEL[state])
        session_usage(db, sid)
    return state


def status(db, project=DEFAULT):
    settings = project_row(db, project)
    models = models_for(settings)
    print(f"项目  {project}  ·  {workspace(settings) or '未绑定目录'}")
    for agent in AGENTS:
        exe = binary(agent)
        last = db.execute("""SELECT c.* FROM calls c JOIN sessions s ON s.id=c.session
                          WHERE s.project=? AND c.agent=? AND (c.model=? OR c.model IS NULL)
                          ORDER BY c.ended IS NULL DESC, COALESCE(c.ended,c.started) DESC LIMIT 1""",
                          (project, agent, models[agent])).fetchone()
        flag = "CLI 就绪，尚未实测" if exe else "缺少 CLI"
        if last and exe:
            clock = time.strftime("%m-%d %H:%M", time.localtime(last["ended"] or last["started"]))
            if last["ended"] is None:
                flag = f"运行中 · {last['stage']} · {clock} 开始"
            elif last["error"]:
                flag = f"最近失败 · {clock} · {last['error'][:160]}"
            elif last["model"] is None:
                flag = f"历史连通（型号未记录）· {clock}"
            else:
                flag = f"最近连通 · {clock}"
        print(f"{agent:7}  {flag}  |  {models[agent] or 'CLI 默认模型'}  |  {exe or '—'}")
        records = db.execute("""SELECT c.usage FROM calls c JOIN sessions s ON s.id=c.session
                             WHERE s.project=? AND c.agent=? AND c.ended IS NOT NULL""", (project, agent))
        totals, missing, reported = 0, 0, 0
        for row in records:
            tokens = json.loads(row["usage"] or "{}").get("total")
            if tokens is None:
                missing += 1
            else:
                totals += tokens
                reported += 1
        print(f"         项目累计 {totals:,} token（{reported} 次有回执，{missing} 次用量未知）")
    print("claude   预留 · 未接入")


def show(db, sid, project=DEFAULT):
    row = session(db, sid, project)
    print(f"\n{row['topic']}\n{LABEL[row['state']]} · {sid}")
    session_usage(db, sid)
    if row["parent"]:
        print("接续记录 " + row["parent"])
    if row["workspace"]:
        print("实施目录 " + row["workspace"])
    for c in db.execute("SELECT * FROM calls WHERE session=? ORDER BY id", (sid,)):
        selected = "旧记录，型号未记录" if c["model"] is None else (c["model"] or "CLI 默认")
        print(f"\n[{c['stage']} · {c['agent']} · {selected}]  {amount(json.loads(c['usage'] or '{}'))}\n"
              + ("\n".join(filter(None, (c["error"], c["reply"]))) or "等待回复"))


def recent(db, project=DEFAULT):
    print(f"项目「{project}」的讨论记录")
    for row in db.execute("SELECT id,state,topic FROM sessions WHERE project=? AND trash_root IS NULL ORDER BY started DESC LIMIT 30", (project,)):
        print(f"{row['id']}  {LABEL[row['state']]}  {row['topic'].splitlines()[0][:70]}")


async def chat(db, sid, project):
    if sid:
        show(db, sid, project)
    status(db, project)
    print("\n" + HELP)
    while True:
        try:
            line = input(f"\n{project}{(' ' + sid) if sid else ''} > ").strip()
        except EOFError:
            break
        if not line:
            continue
        cmd, _, arg = line.partition(" ")
        arg = arg.strip()
        try:
            if not line.startswith("/"):
                sid = await begin(db, line, sid, project=project)
            elif cmd == "/quit":
                break
            elif cmd == "/new":
                sid = None
            elif cmd == "/help":
                print(HELP)
            elif cmd == "/project":
                new = project_command(db, project, shlex.split(arg), interactive=True)
                if new != project:
                    project, sid = new, None
            elif cmd == "/model":
                model_command(db, project, shlex.split(arg), interactive=True)
            elif cmd == "/open":
                show(db, arg, project)
                sid = arg
            elif cmd == "/list":
                recent(db, project)
            elif cmd == "/show":
                show(db, arg or sid, project)
            elif cmd == "/status":
                status(db, project)
            elif cmd == "/probe":
                await begin(db, "连接测试", probe=True, project=project)
            elif cmd == "/ask":
                agent, _, question = arg.partition(" ")
                if agent not in AGENTS or not question.strip():
                    raise ValueError("用法：/ask codex 问题 或 /ask gemini 问题")
                sid = await begin(db, question, sid, agent, project=project)
            elif cmd == "/run":
                await implement(db, sid, arg, project)
            else:
                print(HELP)
        except (ValueError, OSError) as exc:
            print(str(exc), file=sys.stderr)


def main():
    p = argparse.ArgumentParser(description="Codex × Gemini 科研与开发圆桌")
    p.add_argument("-p", "--project", metavar="项目名", help="本次使用的项目，优先于上次选择")
    sub = p.add_subparsers(dest="cmd")
    web = sub.add_parser("web", help="打开本地圆桌窗口")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--no-open", action="store_true", help="打印地址，手动打开浏览器")
    for command, help_text in (("project", PROJECT_HELP), ("model", MODEL_HELP)):
        parser = sub.add_parser(command, description=help_text, help=help_text)
        parser.add_argument("arguments", nargs="*", metavar="参数")
    sub.add_parser("stop", help="停止正在运行的讨论或实施").add_argument("id")
    sub.add_parser("quota", help="读取 CLI 的账号订阅额度").add_argument("agent", choices=AGENTS)
    check = sub.add_parser("status", help="查看连接与累计用量")
    check.add_argument("--probe", action="store_true", help="各发送一次真实请求")
    shell = sub.add_parser("chat", help="进入交互模式")
    shell.add_argument("--terminal", action="store_true", help="使用纯终端界面")
    shell.add_argument("--after", metavar="ID", help="接续已有对话")
    for name in ("discuss", "ask"):
        q = sub.add_parser(name, help="讨论议题" if name == "discuss" else "与一个模型聊天")
        if name == "ask":
            q.add_argument("agent", choices=AGENTS)
        else:
            q.add_argument("--rounds", type=int, choices=(1, 2, 3), default=2, help="最多表决几版方案")
        q.add_argument("topic", help="议题文本，用 - 从标准输入读取")
        q.add_argument("--after", metavar="ID", help="接续已有对话")
    sub.add_parser("list", help="最近的讨论记录")
    sub.add_parser("show", help="查看逐轮记录与 token").add_argument("id")
    run = sub.add_parser("implement", help="把已达成共识的方案交给 Codex 执行")
    run.add_argument("id")
    run.add_argument("--workspace", help="本次实施目录，默认使用项目绑定的目录")
    args = p.parse_args()
    if args.cmd in (None, "web") or (args.cmd == "chat" and sys.stdin.isatty() and not args.terminal):
        from local_ui import serve
        return serve(getattr(args, "port", 8765), not getattr(args, "no_open", False),
                     args.project, getattr(args, "after", None))
    previous_mask = os.umask(0o077)
    try:
        db = database()
    finally:
        os.umask(previous_mask)
    try:
        project = project_row(db, args.project)["name"]
        if args.cmd == "project":
            project_command(db, project, args.arguments, interactive=sys.stdin.isatty())
        elif args.cmd == "model":
            model_command(db, project, args.arguments, interactive=sys.stdin.isatty())
        elif args.cmd in (None, "chat"):
            asyncio.run(chat(db, getattr(args, "after", None), project))
        elif args.cmd == "stop":
            request_stop(db, args.id, project)
            print("已请求停止，已收到的发言保留在讨论记录中。")
        elif args.cmd == "quota":
            from quotas import read_quota
            print(json.dumps(read_quota(args.agent), ensure_ascii=False, indent=2))
        elif args.cmd == "status":
            if args.probe:
                sid = asyncio.run(begin(db, "连接测试", probe=True, project=project))
                status(db, project)
                return int(session(db, sid, project)["state"] != "probe")
            status(db, project)
        elif args.cmd == "list":
            recent(db, project)
        elif args.cmd == "show":
            show(db, args.id, project)
        elif args.cmd == "implement":
            return int(asyncio.run(implement(db, args.id, args.workspace, project)) != "returned")
        else:
            topic = sys.stdin.read().strip() if args.topic == "-" else args.topic
            sid = asyncio.run(begin(db, topic, args.after, getattr(args, "agent", None), getattr(args, "rounds", 2), project=project))
            state = session(db, sid, project)["state"]
            return 2 if state == "disputed" else int(state in ("incomplete","stopped"))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, sqlite3.Error) as exc:
        sys.exit(str(exc))
    except KeyboardInterrupt:
        sys.exit(130)
