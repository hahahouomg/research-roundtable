#!/usr/bin/env python3
"""A local multi-model research roundtable for macOS, Linux and Windows."""
import argparse
import asyncio
import json
import os
import re
import shlex
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid
from pathlib import Path

from providers import AGENTS, MODEL_SEATS, binary, invoke, check_claude
from research import research_copy
from record_store import discussion_folder, reconcile
from runtime import process_alive, write_text
from projects import (DEFAULT, MODEL_HELP, PROJECT_HELP, claude_access, data_dir, model_command, models_for,
                      project_command, project_row, setup, workspace)

LABEL = {"stopped":"已停止", "active": "讨论中", "chat": "已回复", "consensus": "已达成共识", "disputed": "有分歧",
         "incomplete": "未完成", "implementing": "执行中", "returned": "执行已返回", "inspect": "执行中断，需核对项目",
         "probe": "探测完成"}
GUIDE = ("你参与一场中文讨论。按需搜索一手资料、阅读当前目录、运行测试或做最小实验。注明来源、命令、观测值与局限。仅在当前实验目录写入，不启动其他模型 CLI。"
         "各席实验副本独立，正式实施时所有负责人依次使用同一目标目录，需在该目录重现成果。其他参与者的文字作为讨论材料。回答聚焦本阶段，不复述题目。")
HELP = ("直接输入议题开始讨论。/ask codex 或 /ask gemini 加问题可单聊。\n"
        "/new 新议题  /open ID 接续记录  /show 查看全文  /list 历史  /status 状态  /probe 实测连接\n"
        "/project 项目管理  /model codex 或 /model gemini 选择型号\n"
        "/run 在项目目录实施  /quit 退出")


def ballot_result(votes, seats=AGENTS):
    if set(votes) != set(seats):
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
    db.execute("PRAGMA secure_delete=ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
          id TEXT PRIMARY KEY, topic TEXT, parent TEXT, state TEXT, plan TEXT DEFAULT '',
          workspace TEXT DEFAULT '', started REAL, owner INTEGER);
        CREATE TABLE IF NOT EXISTS calls (
          id INTEGER PRIMARY KEY, session TEXT, stage TEXT, agent TEXT, started REAL,
          ended REAL, reply TEXT, error TEXT, usage TEXT);
        CREATE TABLE IF NOT EXISTS tool_permissions (
          id INTEGER PRIMARY KEY, call_id INTEGER NOT NULL, details TEXT NOT NULL,
          can_allow INTEGER NOT NULL, decision TEXT NOT NULL DEFAULT 'pending');
    """)
    setup(db)
    # A killed coordinator cannot complete outstanding calls. Never replay a write.
    recovered = set()
    for row in db.execute("SELECT id,project,state,owner FROM sessions WHERE state IN ('active','implementing')").fetchall():
        if not process_alive(row["owner"]):
            state = "inspect" if row["state"] == "implementing" else "incomplete"
            if db.execute("UPDATE sessions SET state=? WHERE id=? AND state=? AND owner IS ?",
                          (state, row["id"], row["state"], row["owner"])).rowcount:
                recovered.add((row["id"],row["project"]))
                db.execute("UPDATE calls SET ended=?,error='进程已中断' WHERE session=? AND ended IS NULL AND owner IS NULL",
                           (time.time(), row["id"]))
    # Writing and typesetting can run in another process after the vote has closed.
    for (pid,) in db.execute("SELECT DISTINCT owner FROM calls WHERE ended IS NULL AND owner IS NOT NULL").fetchall():
        if not process_alive(pid):
            for (sid, project) in db.execute("""SELECT DISTINCT s.id,s.project FROM sessions s JOIN calls c ON c.session=s.id
                                               WHERE c.owner=? AND c.ended IS NULL""", (pid,)):
                recovered.add((sid,project))
            db.execute("UPDATE calls SET ended=?,error='调用进程已中断' WHERE owner=? AND ended IS NULL",
                       (time.time(), pid))
    db.execute("""UPDATE tool_permissions SET decision='expired' WHERE decision='pending' AND
                  call_id IN (SELECT id FROM calls WHERE ended IS NOT NULL)""")
    reconcile(db, save_finished_record)
    for sid,project in recovered:
        if db.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone():
            save_finished_record(db,sid,project)
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
            if row["state"] == "stopped" or not row["plan"] or call["stage"].startswith("表决") or call["stage"] in ("实施", "集成复核"):
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
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("UPDATE sessions SET state=CASE WHEN stop_requested=1 THEN 'stopped' ELSE ? END WHERE id=?", (state,sid))
        state, project = db.execute("SELECT state,project FROM sessions WHERE id=?", (sid,)).fetchone()
        db.commit()
    except BaseException:
        db.rollback()
        raise
    save_finished_record(db, sid, project)
    return state


def decide_tool(db, sid, project, request_id, decision):
    session(db, sid, project)
    if decision not in ("allow", "deny"):
        raise ValueError("无效的授权决定")
    changed = db.execute("""UPDATE tool_permissions SET decision=? WHERE id=? AND decision='pending'
                AND (can_allow=1 OR ?='deny') AND call_id IN (SELECT c.id FROM calls c
                JOIN sessions s ON s.id=c.session WHERE s.id=? AND c.ended IS NULL AND s.stop_requested=0)""",
                (decision, request_id, decision, sid)).rowcount
    if not changed:
        raise ValueError("该请求已处理、已失效或未提供单次授权")


async def call(db, sid, stage, agent, prompt, selected_model, workspace=None, ballot=False, schema=None, use_tools=True):
    entry = db.execute("SELECT settings,project FROM sessions WHERE id=?", (sid,)).fetchone()
    if not entry:
        return None
    saved, project = entry
    preferences = project_row(db, project)
    folder = discussion_folder(project, sid)
    def stopping():
        row = db.execute("SELECT stop_requested FROM sessions WHERE id=?", (sid,)).fetchone()
        return not row or row[0] or not folder.is_dir()
    if stopping():
        return None
    start = time.time()
    settings = json.loads(saved or "{}")
    effort = settings.get("efforts", {}).get(agent, settings.get("effort") if agent == "codex" else None)
    created = db.execute("""INSERT INTO calls(session,stage,agent,started,model,effort,owner) SELECT ?,?,?,?,?,?,?
                         WHERE EXISTS(SELECT 1 FROM sessions WHERE id=? AND stop_requested=0)""",
                         (sid, stage, agent, start, selected_model, effort, os.getpid(), sid))
    if not created.rowcount:
        return None
    cid = created.lastrowid
    if stopping():
        db.execute("UPDATE calls SET ended=?,error='讨论已停止' WHERE id=?", (time.time(),cid))
        return None
    print(f"  · {stage}  {agent} · {selected_model or 'CLI 默认'} …", flush=True)
    def preview(text):
        db.execute("UPDATE calls SET reply=? WHERE id=?", (text, cid))

    def auto_lab():
        return bool(db.execute("""SELECT p.gemini_auto_lab FROM projects p JOIN sessions s ON p.name=s.project
                                  WHERE s.id=?""", (sid,)).fetchone()[0])
    async def permission(tool, can_allow, isolated=False):
        # Preserve the vendor's exact command, diff, or path for inspection before deciding.
        details = {k: tool[k] for k in ("title", "kind", "rawInput", "args", "locations", "content") if tool.get(k)}
        details["cwd"] = str(workspace)
        can_allow = can_allow and any(details.get(k) for k in ("rawInput", "args", "locations", "content"))
        if isolated and can_allow and auto_lab() and not stopping():
            db.execute("INSERT INTO tool_permissions(call_id,details,can_allow,decision) VALUES(?,?,1,'auto')",
                       (cid, json.dumps(details, ensure_ascii=False)))
            return True
        pid = db.execute("INSERT INTO tool_permissions(call_id,details,can_allow) VALUES(?,?,?)",
                         (cid, json.dumps(details, ensure_ascii=False), int(can_allow))).lastrowid
        print(f"  · {stage} Gemini 正等待网页确认 · {sid} · {tool.get('title') or '工具'}", flush=True)
        try:
            while True:
                decision = db.execute("SELECT decision FROM tool_permissions WHERE id=?", (pid,)).fetchone()[0]
                if decision != "pending":
                    return decision == "allow"
                await asyncio.sleep(0.35)
        finally:
            db.execute("UPDATE tool_permissions SET decision='expired' WHERE id=? AND decision='pending'", (pid,))

    job = asyncio.create_task(invoke(agent, prompt, workspace=workspace, ballot=ballot,
                                     selected_model=selected_model, on_text=preview, effort=effort, schema=schema, probe=stage=="连接测试" or not use_tools,
                                     implementing=stage in ("实施", "集成复核"), reviewing=stage=="集成复核",
                                     isolated_lab=agent=="gemini" and auto_lab() and stage not in ("实施", "集成复核", "连接测试"),
                                     check_access=claude_access(db, project) if agent=="claude" else None,
                                     timeout_seconds=(preferences["call_minutes"] or 0)*60 or None, gemini_mode=preferences["gemini_mode"],
                                     on_permission=permission, on_tool=lambda title: preview("正在使用工具 · " + title)))
    try:
        while not job.done():
            await asyncio.wait([job], timeout=0.3)
            if not job.done() and stopping():
                job.cancel()
                break
        reply, usage = await job
    except (OSError, ValueError, asyncio.TimeoutError, asyncio.CancelledError) as exc:
        error = str(exc) or ("调用超时" if isinstance(exc, asyncio.TimeoutError) else "已中断")
        if re.search(r"rate.limit|resource.exhausted|usage limit|quota.exceeded|额度耗尽|\b429\b", error, re.I):
            error = "额度或频率受限 · " + error
        elif re.search(r"content.filter|safety.block|blocked.by.safety|stopReason.*refusal|未完成本轮：refusal", error, re.I):
            error = "服务方内容安全限制 · " + error
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


def plan_schema(seats):
    task = {"type": "object", "additionalProperties": False, "required": ["owner", "task", "acceptance"],
            "properties": {"owner": {"type": "string", "enum": list(seats)},
                           "task": {"type": "string"}, "acceptance": {"type": "string"}}}
    return {"type": "object", "additionalProperties": False, "required": ["plan", "tasks"],
            "properties": {"plan": {"type": "string"}, "tasks": {"type": "array", "items": task}}}


def read_plan(reply, seats):
    candidate = json.loads(reply)
    if not isinstance(candidate, dict) or not isinstance(candidate.get("plan"), str) or not candidate["plan"].strip():
        raise ValueError("候选方案缺少正文")
    tasks = candidate.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("候选方案缺少任务分工")
    lines = [candidate["plan"], "\n实施顺序"]
    for i, task in enumerate(tasks, 1):
        if (not isinstance(task, dict) or not isinstance(task.get("owner"), str) or task["owner"] not in seats or
            not all(isinstance(task.get(k), str) and task[k].strip() for k in ("task", "acceptance"))):
            raise ValueError("候选方案中的负责人、任务或验收条件无效")
        lines.append(f"{i}. {task['owner']} · {task['task']}（验收：{task['acceptance']}）")
    return "\n".join(lines), tasks


async def write_final(db, sid, source, plan, votes, model, folder):
    writer_prompt = ("你是共识通过后的最终执笔人。给议题的读者写一份可直接下载使用、通俗准确的中文 Markdown 方案。"
              "先讲要解决的具体问题，再解释为何选择这个方向、怎样验证、何时停止和谁负责。"
              "忠实保留表决稿的目标、范围、数字、单位、验收条件、分工及不确定性。"
              "任何票中新增建议须单列为审阅备注，不得写成已通过的条件。用自己的文字解释术语。"
              "仅引用材料里已有的来源，区分观测和预测。直接交付完整正文。\n"
              + source + "\n全体通过的原文：\n" + plan + "\n本版表决原文：\n" + bundle(votes))
    written = await call(db, sid, "最终方案撰写", "gemini", writer_prompt, model, workspace=folder)
    if written is None:
        db.execute("UPDATE sessions SET failure=? WHERE id=?", ("全体已通过；Gemini 定稿尚未完成，可续跑此轮。", sid))
    return written


def cross_review_prompt(base, proposals):
    return (base + "逐一点评其余席位，点名对方并准确复述其主张。说明赞同之处、最重要的分歧或漏洞，"
            "给出能区分解释的一项检验。已有来源不必重复检索，确有证据缺口可用工具。无实质分歧时直接说明。\n"
            + bundle(proposals))


async def discuss(db, sid, topic, rounds, models, folders):
    lead = moderator_for(db, sid, models)
    async def phase(stage, agent, prompt, *, ballot=False, schema=None):
        saved = db.execute("""SELECT reply FROM calls WHERE session=? AND stage=? AND agent=? AND ended IS NOT NULL
                              AND error IS NULL ORDER BY id DESC LIMIT 1""", (sid, stage, agent)).fetchone()
        if saved and saved["reply"]:
            reply = saved["reply"]
            valid = not ballot or ballot_result({agent: reply}, (agent,)) != "incomplete"
            if schema:
                try:
                    read_plan(reply, models)
                except ValueError:
                    valid = False
            if valid:
                return reply
        prior = db.execute("SELECT error,reply FROM calls WHERE session=? AND stage=? AND agent=? ORDER BY id DESC LIMIT 1",
                           (sid, stage, agent)).fetchone()
        if prior and prior["error"] and ("权限被拒绝" in prior["error"] or "工具请求已拒绝" in prior["error"]):
            prompt += ("\n补交本席本阶段回复。请实际使用工具核验影响你判断的一项事实或数值，"
                       "记录操作和结果。需要确认时，通过工具请求向圆桌网页申请授权。")
        if prior and prior["error"] == "调用超时" and stage.startswith("候选方案"):
            prompt += ("\n上一次主持汇总到时中断。请直接接续已完成的评议和核算，优先提交可供表决的结构化候选稿。"
                       "如工作区有本席保存的讨论实验，可读取其结果；将需要未来实验的分歧列入验证设计。"
                       "\n本席中断前最后一条进度：\n" + (prior["reply"] or "未收到正文")[-1800:])
        return await call(db, sid, stage, agent, prompt, models[agent], workspace=folders[agent],
                          ballot=ballot, schema=schema)

    async def ask_seats(stage, prompt, ballot=False):
        replies = await asyncio.gather(*(phase(stage, a, prompt, ballot=ballot) for a in models))
        if None in replies:
            raise ValueError(f"{stage} 未收齐全部席位回复，已保存现有记录")
        if not ballot:
            for agent, reply in zip(models, replies):
                print(f"\n{agent} · {stage}\n{reply}", flush=True)
        return dict(zip(models, replies))

    base = f"{GUIDE}\n用户议题及已提供背景：\n{topic}\n"
    proposals = await ask_seats("独立提案", base + "独立给出你的方案和最大不确定性。科研题写可证伪假设、最小实验和基线；"
                           "开发题写交付和验收。按任务规模控制篇幅，通常在 350 字内。")
    drafts = bundle(proposals)
    reviews = await ask_seats("交叉评议", cross_review_prompt(base, proposals))
    source = base + "\n提案：\n" + drafts + "\n交叉评议：\n" + bundle(reviews)
    revision = ""
    for version in range(1, rounds + 1):
        candidate = await phase(f"候选方案 v{version}", lead, source + revision +
                          "\n拟定一份可独立使用的方案，写清取舍、待验证假设、最小下一步、分工和可检查的验收条件。"
                          "科研议题写出能否定假设的结果。小任务保持简短，将实现细节留给负责人。保留真正未解决的选择。"
                          f"参与者为 {', '.join(models)}。输出 plan 和按依赖排序的 tasks，每项含 owner、task、acceptance。"
                          + ("在 Windows 原生部署下，实施任务请分给 Codex 或 Gemini。\n" if os.name == "nt" else "") +
                          "按题目分工，后端、算法优先 Codex，前端和交互优先 Gemini；小事可只派一席。"
                          "开发任务分别写明负责的目录或文件、共享接口的唯一负责人和可运行的验收命令。"
                          "逐项说明交叉评议中的主要分歧、取舍理由和仍待实验的问题。"
                          "请复用三席已查证的资料和实验结果，只对会改变取舍的问题补证。把后续实验写成验收条件，详细报告由表决后的执笔人撰写。"
                          f"跨席实施完成后系统另行派 {reviewer_for(lead)} 做只读集成复核。",
                          schema=plan_schema(models))
        if candidate is None:
            raise ValueError("候选方案生成失败")
        plan, tasks = read_plan(candidate, models)
        db.execute("UPDATE sessions SET plan=?,assignments=? WHERE id=?", (plan, json.dumps(tasks, ensure_ascii=False), sid))
        print(f"\n候选方案 v{version}\n{plan}\n", flush=True)
        votes = await ask_seats(f"表决 v{version}", source + "\n请就下列这份候选方案独立表决。"
                           "可接受以验证假设为下一步的计划。复用已有实测结果，仅为影响结论的证据缺口补测。实质阻碍才反对，指出最小修订。"
                           '只输出 JSON {"vote":"accept 或 object","reason":"明确理由"}。\n候选方案：\n' + plan, True)
        for agent, vote in votes.items():
            print(f"  {agent}  {vote}", flush=True)
        decision = ballot_result(votes, models)
        if decision == "consensus":
            await write_final(db, sid, source, plan, votes, models["gemini"], folders["gemini"])
            return decision
        if decision == "incomplete":
            print("有表决缺少有效的选项或理由。原始回复已保存。", file=sys.stderr)
        if decision != "disputed":
            return decision
        revision = "\n上一版候选方案：\n" + plan + "\n上一版表决：逐项解决阻塞问题，保留已同意的部分，不把可选建议升级为新的验收条件。\n\n" + bundle(votes)
    return "disputed"


def reviewer_for(moderator):
    return "claude" if moderator == "claude" else "codex"


def moderator_for(db, sid, models):
    settings, = db.execute("SELECT settings FROM sessions WHERE id=?", (sid,)).fetchone()
    chosen = json.loads(settings or "{}").get("moderator")
    return chosen if chosen in models else ("claude" if "claude" in models else "codex")


def prepare_topic(db, topic, parent, project, moderator="", mode="both"):
    if not topic.strip():
        raise ValueError("议题不能为空")
    row = project_row(db, project)
    models = models_for(row)
    if moderator and moderator not in models:
        raise ValueError("请选择已启用的席位担任主持人")
    settings = dict(models=models, moderator=moderator, mode=mode, efforts={a: row[a+"_effort"] for a in ("codex","claude")}, source=str(workspace(row) or ""))
    past = history(db, parent, project)
    context = f"既往对话：\n{past}\n\n本轮用户原话：\n{topic}" if past else topic
    sid = uuid.uuid4().hex[:12]
    folder = discussion_folder(project, sid)
    folder.mkdir(mode=0o700, parents=True)
    try:
        db.execute("INSERT INTO sessions(id,topic,parent,state,started,owner,project,settings,folder_ready) VALUES(?,?,?,'active',?,?,?,?,1)",
                   (sid, topic, parent, time.time(), os.getpid(), project, json.dumps(settings)))
    except BaseException:
        folder.rmdir()
        raise
    print(f"\n{project} · 记录 {sid}　{topic}", flush=True)
    return sid, context, models


async def begin(db, topic, parent=None, agent=None, rounds=2, probe=False, project=DEFAULT, moderator=""):
    sid, context, models = prepare_topic(db, topic, parent, project, moderator, "probe" if probe else agent or "both")
    return await run_topic(db, sid, context, models, agent, rounds, probe)


async def resume_discussion(db, sid, project, rounds=2):
    row = session(db, sid, project)
    settings = json.loads(row["settings"] or "{}")
    models = settings.get("models") or {}
    stages = {r[0] for r in db.execute("SELECT DISTINCT stage FROM calls WHERE session=?", (sid,))}
    mode = settings.get("mode")
    single = mode if mode in models and mode in MODEL_SEATS else None
    if not models or row["workspace"] or (not single and mode not in ("both", None)):
        raise ValueError("此记录无法在原阶段续跑")
    if mode is None and "独立提案" not in stages:
        raise ValueError("此旧记录未保存续跑所需的席位信息")
    drafting_only = row["state"] == "consensus"
    if drafting_only:
        last = db.execute("SELECT error FROM calls WHERE session=? AND stage='最终方案撰写' ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
        if not last or not last["error"]:
            raise ValueError("该讨论已经完成")
    elif row["state"] not in ("disputed", "incomplete"):
        raise ValueError("只可续跑已中断或仍有分歧的讨论")
    elif (single == "claude" or not single and "claude" in models) and not project_row(db, project)["claude_enabled"]:
        raise ValueError("请先为此项目启用原讨论的 Claude 席位")
    last_version = max((int(s[4:]) for s in stages if s.startswith("表决 v") and s[4:].isdigit()), default=0)
    rounds = max(rounds, last_version + (row["state"] == "disputed"))
    past = history(db, row["parent"], project)
    context = ("既往对话：\n" + past + "\n\n本轮用户原话：\n" if past else "") + row["topic"]
    if not db.execute("UPDATE sessions SET state='active',owner=?,failure=NULL WHERE id=? AND state=? AND stop_requested=0",
                      (os.getpid(),sid,row["state"])).rowcount:
        raise ValueError("讨论已被其他进程接手，或已要求停止")
    if drafting_only:
        votes = dict(db.execute("SELECT agent,reply FROM calls WHERE session=? AND stage=? AND error IS NULL AND ended IS NOT NULL ORDER BY id",
                                (sid,f"表决 v{last_version}")))
        reviews = dict(db.execute("SELECT agent,reply FROM calls WHERE session=? AND stage='交叉评议' AND error IS NULL AND ended IS NOT NULL ORDER BY id",(sid,)))
        try:
            with tempfile.TemporaryDirectory(prefix="roundtable-draft-") as folder:
                await write_final(db,sid,context+"\n交叉评议：\n"+bundle(reviews),row["plan"],votes,models["gemini"],Path(folder))
        finally:
            finish(db,sid,"consensus")
        return sid
    return await run_topic(db, sid, context, models, single, rounds, False, require_all=True)


async def run_topic(db, sid, context, models, agent, rounds, probe, require_all=False):
    state = "incomplete"
    try:
        seats = [agent] if agent else list(models)
        if any(a not in models for a in seats):
            raise ValueError("请先在此项目启用对应席位")
        settings = json.loads(db.execute("SELECT settings FROM sessions WHERE id=?", (sid,)).fetchone()[0])
        if "claude" in seats:
            try:
                await asyncio.to_thread(check_claude)
            except ValueError as exc:
                if agent or probe or require_all:
                    raise
                models = {a: m for a, m in models.items() if a != "claude"}
                seats = list(models)
                settings.update(models=models, moderator=settings.get("moderator") if settings.get("moderator") in models else "codex", notice=f"{exc}。本轮由 Codex 和 Gemini 讨论。")
                db.execute("UPDATE sessions SET settings=? WHERE id=?", (json.dumps(settings), sid))
                print(settings["notice"], flush=True)
        if probe:
            replies = await asyncio.gather(*(call(db, sid, "连接测试", a, "Reply only ROUND_OK. Do not use tools.", models[a]) for a in seats))
            if all(r == "ROUND_OK" for r in replies):
                state = "probe"
        else:
            missing = [a for a in seats if not binary(a)]
            if missing:
                raise ValueError("未找到 " + "、".join(missing) + " 的 CLI")
            source = Path(settings["source"]) if settings["source"] else None
            with tempfile.TemporaryDirectory(prefix="roundtable-lab-") as tmp:
                folders = {a: Path(tmp) / a for a in seats}
                first, *others = folders.values()
                research_copy(source, first)
                for target in others:
                    shutil.copytree(first, target)
                if agent:
                    answer = await call(db, sid, "单聊", agent, GUIDE + "\n" + context, models[agent], workspace=folders[agent])
                    if answer is not None:
                        print("\n" + answer)
                        state = "chat"
                else:
                    state = await discuss(db, sid, context, rounds, models, folders)
    except (ValueError, OSError) as exc:
        db.execute("UPDATE sessions SET failure=? WHERE id=?", (str(exc), sid))
        print(str(exc), file=sys.stderr)
    finally:
        state = finish(db, sid, state)
        print(f"\n{LABEL[state]} · {sid}", flush=True)
        session_usage(db, sid)
    return sid


REPORT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["status", "report"],
                 "properties": {"status": {"type": "string", "enum": ["done", "blocked"]}, "report": {"type": "string"}}}


async def implement(db, sid, destination=None, project=DEFAULT):
    row = session(db, sid, project)
    settings = project_row(db, project)
    target = Path(destination).expanduser().resolve() if destination else workspace(settings)
    if target is None or not target.is_dir():
        raise ValueError("请用 project path 绑定现有目录，或在执行时指定目录")
    tasks = json.loads(row["assignments"] or "null") or [{"owner": "codex", "task": row["plan"], "acceptance": "按已批准方案验收"}]
    models = json.loads(row["settings"] or "{}").get("models", models_for(settings))
    owners = {task["owner"] for task in tasks}
    reviewer = reviewer_for(moderator_for(db, sid, models)) if len(owners) > 1 else None
    if "claude" in owners and os.name == "nt":
        raise ValueError("此方案分配了 Claude 写入任务，请在 macOS/Linux 实施，或发起新一轮调整分工")
    if "claude" in owners or reviewer == "claude":
        if not settings["claude_enabled"]:
            raise ValueError("此方案需要 Claude，请先为当前项目启用 Claude")
        await asyncio.to_thread(check_claude)
    db.execute("BEGIN IMMEDIATE")
    try:
        for other in db.execute("SELECT id,workspace FROM sessions WHERE state='implementing'"):
            path = Path(other["workspace"]).resolve()
            if target == path or path in target.parents or target in path.parents:
                raise ValueError(f"目录正在被讨论 {other['id']} 实施，请在它结束后重试")
        changed = db.execute("UPDATE sessions SET state='implementing',workspace=?,owner=? WHERE id=? AND state='consensus' AND trash_root IS NULL AND project IN (SELECT name FROM projects WHERE trashed=0)",
                             (str(target), os.getpid(), sid)).rowcount
        if not changed:
            raise ValueError(f"当前状态为「{LABEL[row['state']]}」。只有已达成共识且尚未派发的方案可执行。")
        db.commit()
    except BaseException:
        db.rollback()
        raise
    state = "inspect"
    try:
        prompt = (f"本次实施共用的目标目录为 {target}。当前工作目录已设为该目录。\n"
                  "在此目录落实下方用户任务和已同意的方案。遵守项目约定，保留已有改动。"
                  "运行相关验收并报告实际结果、改动和未完成项。不要发布、推送、启动其他模型或联系第三方。\n"
                  + "先前讨论背景：\n" + history(db, row["parent"], project) + "\n本轮用户要求：\n" + row["topic"] + "\n已表决的方案：\n" + row["plan"])
        print(f"实施目录  {target}")
        reports = []
        steps = [("实施", task) for task in tasks]
        if reviewer:
            steps.append(("集成复核", {"owner": reviewer, "task": "只读核对目标目录的实际产物、接口和各项验收证据。可运行只读核验命令，勿修改文件。", "acceptance": "逐项列明复核结果和可复现依据。缺失产物、接口不符或无法核实关键验收条件时返回 blocked。"}))
        for stage, task in steps:
            owner = task["owner"]
            handoff = ("\n仅实施本项：" + task["task"] + "\n验收条件：" + task["acceptance"] +
                       "\n先前交接：" + "\n".join(reports)[-16000:] +
                       "\n若任务未能完成，请将结果标为 blocked，说明原因。")
            answer = await call(db, sid, stage, owner, prompt + handoff, models[owner], workspace=target,
                                schema=REPORT_SCHEMA)
            if not answer:
                break
            try:
                result = json.loads(answer)
            except ValueError:
                result = None
            if not isinstance(result, dict) or not isinstance(result.get("report"), str) or not result["report"].strip():
                db.execute("UPDATE sessions SET failure=? WHERE id=?", (f"{owner} 缺少有效实施报告", sid))
                break
            if result.get("status") != "done":
                db.execute("UPDATE sessions SET failure=? WHERE id=?", (f"{owner} 未完成任务：{result['report']}", sid))
                break
            reports.append(owner + "：" + result["report"])
            print("\n" + reports[-1])
        else:
            state = "returned"
    finally:
        state = finish(db, sid, state)
        print(LABEL[state])
        session_usage(db, sid)
    return state


def status(db, project=DEFAULT):
    settings = project_row(db, project)
    models = models_for(settings)
    print(f"项目  {project}  ·  {workspace(settings) or '未绑定目录'}")
    for agent in models:
        exe = binary(agent)
        last = db.execute("""SELECT c.* FROM calls c JOIN sessions s ON s.id=c.session
                          WHERE s.project=? AND c.agent=? AND (c.model=? OR c.model IS NULL) AND c.effort IS ?
                          ORDER BY c.ended IS NULL DESC, COALESCE(c.ended,c.started) DESC LIMIT 1""",
                          (project, agent, models[agent], settings[agent+"_effort"] if agent in ("codex","claude") else None)).fetchone()
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
    if "claude" not in models:
        print("claude   当前项目未启用")


def show(db, sid, project=DEFAULT):
    row = session(db, sid, project)
    print(f"\n{row['topic']}\n{LABEL[row['state']]} · {sid}")
    session_usage(db, sid)
    notice = json.loads(row["settings"] or "{}").get("notice")
    if notice:
        print(notice)
    if row["failure"]:
        print(row["failure"])
    if row["parent"]:
        print("接续记录 " + row["parent"])
    if row["workspace"]:
        print("实施目录 " + row["workspace"])
    for c in db.execute("SELECT * FROM calls WHERE session=? ORDER BY id", (sid,)):
        selected = "旧记录，型号未记录" if c["model"] is None else (c["model"] or "CLI 默认")
        if c["effort"]:
            selected += " · " + c["effort"]
        print(f"\n[{c['stage']} · {c['agent']} · {selected}]  {amount(json.loads(c['usage'] or '{}'))}\n"
              + ("\n".join(filter(None, (c["error"], c["reply"]))) or "等待回复"))


def recent(db, project=DEFAULT):
    print(f"项目「{project}」的讨论记录")
    for row in db.execute("SELECT id,state,topic FROM sessions WHERE project=? AND trash_root IS NULL ORDER BY started DESC LIMIT 30", (project,)):
        print(f"{row['id']}  {LABEL[row['state']]}  {row['topic'].splitlines()[0][:70]}")


def transcript(db, sid, project):
    row = session(db, sid, project)
    def clock(epoch):
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(epoch)) if epoch else "—"
    sections = [f"# {project} · 圆桌讨论记录", f"编号 `{sid}` · {LABEL[row['state']]} · {clock(row['started'])}",
                "## 用户议题", row["topic"]]
    for label, value in [("接续自", row["parent"]), ("实施目录", row["workspace"]), ("异常", row["failure"]),
                         ("席位说明", json.loads(row["settings"] or "{}").get("notice"))]:
        if value:
            sections.append(f"{label} · {value}")
    for i, c in enumerate(db.execute("SELECT * FROM calls WHERE session=? ORDER BY id", (sid,)), 1):
        sections.extend([f"## {i}. {c['stage']} · {c['agent']}",
                         " · ".join(filter(None, (c["model"] or "CLI 默认", c["effort"], clock(c["started"]),
                                                  clock(c["ended"]), amount(json.loads(c["usage"] or "{}")))))])
        for perm in db.execute("SELECT details,decision FROM tool_permissions WHERE call_id=? ORDER BY id", (c["id"],)):
            label = {"pending": "等待确认", "allow": "允许一次", "auto": "隔离实验自动允许", "deny": "拒绝", "expired": "已失效"}[perm["decision"]]
            details = json.dumps(json.loads(perm["details"]), ensure_ascii=False, indent=2)
            sections.append("Gemini 工具确认 · " + label + "\n\n<details><summary>完整工具参数</summary>\n\n~~~~json\n" +
                            details + "\n~~~~\n\n</details>")
        if c["error"]:
            sections.append("调用异常 · " + c["error"])
        reply = c["reply"] or "（没有收到正文）"
        try:
            obj = json.loads(reply)
            readable = ""
            if c["stage"].startswith("候选方案"):
                readable, _ = read_plan(reply, json.loads(row["settings"] or "{}").get("models", MODEL_SEATS))
            elif c["stage"].startswith("表决"):
                readable = {"accept":"赞成", "object":"反对"}[obj["vote"]] + " · " + obj["reason"]
            elif c["stage"] in ("实施", "集成复核"):
                readable = obj["status"] + " · " + obj["report"]
            if readable:
                sections.append(readable)
                reply = "<details><summary>原始结构化回执</summary>\n\n```json\n" + reply + "\n```\n\n</details>"
        except (ValueError, KeyError, TypeError):
            pass
        if c["stage"] == "图文 PDF 排版" and "<html" in reply.lower():
            fence = "~" * (max((len(line) - len(line.lstrip("~")) for line in reply.splitlines()), default=0) + 4)
            reply = "<details><summary>Gemini 图文排版原始回执</summary>\n\n" + fence + "text\n" + reply + "\n" + fence + "\n\n</details>"
        sections.append(reply)
    return "\n\n".join(sections) + "\n"


def save_finished_record(db, sid, project):
    try:
        persist_record(db, sid, project)
    except OSError:
        db.execute("UPDATE sessions SET failure=COALESCE(failure,?) WHERE id=?",
                   ("记录文件夹无法写入。发言仍可在网页查看及下载。", sid))


def persist_record(db, sid, project):
    folder = discussion_folder(project, sid)
    if not folder.is_dir():
        return
    try:
        text = transcript(db, sid, project)
        row = session(db, sid, project)
        write_text(folder / "讨论记录.md", text)
        if row["plan"]:
            final = db.execute("""SELECT reply FROM calls WHERE session=? AND stage='最终方案撰写'
                                  AND ended IS NOT NULL AND error IS NULL ORDER BY id DESC LIMIT 1""", (sid,)).fetchone()
            write_text(folder / "方案.md", ((final and final["reply"]) or row["plan"]) + "\n")
    except (FileNotFoundError, ValueError):
        if folder.is_dir():
            raise


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
                if agent not in (*AGENTS, "claude") or not question.strip():
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
    sub.add_parser("quota", help="读取 CLI 的账号订阅额度").add_argument("agent", choices=MODEL_SEATS)
    check = sub.add_parser("status", help="查看连接与累计用量")
    check.add_argument("--probe", action="store_true", help="各发送一次真实请求")
    shell = sub.add_parser("chat", help="进入交互模式")
    shell.add_argument("--terminal", action="store_true", help="使用纯终端界面")
    shell.add_argument("--after", metavar="ID", help="接续已有对话")
    for name in ("discuss", "ask"):
        q = sub.add_parser(name, help="讨论议题" if name == "discuss" else "与一个模型聊天")
        if name == "ask":
            q.add_argument("agent", choices=(*AGENTS, "claude"))
        else:
            q.add_argument("--moderator", choices=MODEL_SEATS, help="主持候选方案及修订")
            q.add_argument("--rounds", type=int, choices=(1, 2, 3), default=2, help="最多表决几版方案")
        q.add_argument("topic", help="议题文本，用 - 从标准输入读取")
        q.add_argument("--after", metavar="ID", help="接续已有对话")
    sub.add_parser("list", help="最近的讨论记录")
    sub.add_parser("show", help="查看逐轮记录与 token").add_argument("id")
    sub.add_parser("export", help="向标准输出导出本轮 Markdown 记录").add_argument("id")
    pdf = sub.add_parser("pdf", help="请 Gemini 将定稿排版为图文 PDF")
    pdf.add_argument("id")
    pdf.add_argument("--evidence", help="可选的文献数据文本，供 Gemini 制图时引用")
    resume = sub.add_parser("resume", help="沿用已返回的发言，从中断的讨论阶段续跑")
    resume.add_argument("id")
    resume.add_argument("--rounds", type=int, choices=(1, 2, 3), default=2, help="本轮最多审议的版本数")
    run = sub.add_parser("implement", help="按已达成共识的分工实施")
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
        elif args.cmd == "export":
            print(transcript(db, args.id, project), end="")
        elif args.cmd == "pdf":
            from reports import export_pdf
            print(asyncio.run(export_pdf(db, args.id, project, args.evidence)))
        elif args.cmd == "resume":
            asyncio.run(resume_discussion(db, args.id, project, args.rounds))
            row = session(db, args.id, project)
            return 2 if row["state"] == "disputed" else int(row["state"] != "consensus" or bool(row["failure"]))
        elif args.cmd == "quota":
            from quotas import read_quota
            if args.agent not in models_for(project_row(db, project)):
                raise ValueError("项目未启用此席位")
            print(json.dumps(read_quota(args.agent, claude_access(db, project) if args.agent=="claude" else None), ensure_ascii=False, indent=2))
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
            sid = asyncio.run(begin(db, topic, args.after, getattr(args, "agent", None), getattr(args, "rounds", 2), project=project, moderator=getattr(args, "moderator", None) or ""))
            row = session(db, sid, project)
            return 2 if row["state"] == "disputed" else int(row["state"] in ("incomplete","stopped") or bool(row["failure"]))
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
