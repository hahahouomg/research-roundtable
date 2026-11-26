"""Bridge agy's sandboxed ACP session to one-shot decisions in the local workspace."""
import asyncio
import json
from pathlib import Path
from runtime import PROCESS_GROUP, stop_process


def execution_mode(available, auto_edits, preference="auto", current="default"):
    if preference == "review":
        return "default"
    if preference == "cli":
        return current
    path = Path.home() / ".gemini/antigravity-cli/settings.json"
    try:
        saved = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (ValueError, OSError):
        return "default"
    policy = saved.get("toolPermission") if isinstance(saved, dict) else "strict"
    if policy in ("strict", "request-review", "always-proceed"):
        return "default"
    if "auto" in available and policy != "proceed-in-sandbox":
        return "auto"
    if auto_edits and "accept-edits" in available:
        return "accept-edits"
    return "default"


async def run(exe, folder, prompt, model, schema, timeout, log, on_text, on_permission, on_tool, auto_edits=False, preference="auto"):
    args = [exe, "acp", "--sandbox", "--log-file", str(log)]
    if preference == "review":
        args += ["--settings", json.dumps({"toolPermission": "strict"})]
    diagnostics = log.with_name("agy-stderr.log")
    with diagnostics.open("wb") as stderr:
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=folder, **PROCESS_GROUP,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=stderr,
            limit=16 * 1024 * 1024)
    seq = 0
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    session = None
    chunks = []
    usage = {}
    tools = {}

    async def send(message):
        proc.stdin.write((json.dumps({"jsonrpc": "2.0", **message}) + "\n").encode())
        await proc.stdin.drain()

    async def request(method, params):
        nonlocal seq, deadline
        seq += 1
        await send({"id": seq, "method": method, "params": params})
        while True:
            line = await asyncio.wait_for(proc.stdout.readline(), max(0, deadline - loop.time()))
            if not line:
                with diagnostics.open("rb") as stderr:
                    stderr.seek(max(0,diagnostics.stat().st_size-650))
                    detail = stderr.read().decode("utf-8",errors="replace").strip()
                raise ValueError("Gemini ACP 会话已关闭" + (f" · {detail}" if detail else ""))
            msg = json.loads(line)
            event = msg.get("method")
            if not event:
                if msg.get("id") != seq:
                    continue
                if "error" in msg:
                    raise ValueError("Gemini ACP · " + str(msg["error"].get("message") or msg["error"]))
                return msg["result"]
            data = msg.get("params", {})
            if event == "session/update" and data.get("sessionId") == session:
                update = data["update"]
                kind = update.get("sessionUpdate")
                if kind == "agent_message_chunk" and update.get("content", {}).get("type") == "text":
                    chunks.append(update["content"]["text"])
                    if on_text:
                        on_text("".join(chunks))
                elif kind in ("tool_call", "tool_call_update"):
                    tool = tools.setdefault(update["toolCallId"], {})
                    tool.update({k: v for k, v in update.items() if v is not None})
                    if kind == "tool_call":
                        chunks.clear()
                        if on_tool:
                            on_tool(tool.get("title") or tool.get("kind") or "工具")
                    elif on_text and update.get("status") in ("completed", "failed"):
                        verb = "已完成" if update["status"] == "completed" else "执行失败"
                        on_text("工具" + verb + " · " + (tool.get("title") or tool.get("kind") or "工具"))
            elif event == "session/request_permission" and data.get("sessionId") == session:
                tool = {**tools.get(data["toolCall"]["toolCallId"], {}), **data["toolCall"]}
                options = {o["kind"]: o["optionId"] for o in data["options"]}
                # Only the vendor's single-use option can authorize work.
                start = loop.time()
                allowed = await on_permission(tool, "allow_once" in options) if on_permission else False
                deadline += loop.time() - start
                choice = options.get("allow_once" if allowed else "reject_once")
                outcome = {"outcome": "selected", "optionId": choice} if choice else {"outcome": "cancelled"}
                await send({"id": msg["id"], "result": {"outcome": outcome}})
                if not allowed or not choice:
                    raise ValueError("Gemini 本次工具请求已拒绝，本席已停止")
            elif "id" in msg:
                await send({"id": msg["id"], "error": {"code": -32601, "message": "Client method unavailable"}})

    try:
        await request("initialize", {"protocolVersion": 1, "clientCapabilities": {},
                      "clientInfo": {"name": "research-roundtable", "version": "1"}})
        info = await request("session/new", {"cwd": str(folder), "mcpServers": []})
        session = info["sessionId"]
        models = info.get("models", {})
        if model and models.get("currentModelId") != model:
            await request("session/set_model", {"sessionId": session, "modelId": model})
        modes = info.get("modes", {})
        available = {item["id"] for item in modes.get("availableModes", [])}
        current = modes.get("currentModeId")
        mode = execution_mode(available, auto_edits, preference, current)
        if available and current != mode and (mode == "default" or mode in available):
            try:
                await request("session/set_mode", {"sessionId": session, "modeId": mode})
            except ValueError:
                if mode == "default" or current not in ("default", "plan", "accept-edits"):
                    raise
                mode = current
        if on_tool and preference == "auto" and mode != "auto":
            on_tool("Gemini 沿用 CLI 工具权限，额外操作在网页确认")
        if schema:
            prompt += "\n最后一条回复仅输出符合以下 schema 的 JSON 对象：\n" + json.dumps(schema, ensure_ascii=False)
        result = await request("session/prompt", {"sessionId": session, "prompt": [{"type": "text", "text": prompt}]})
        if result.get("stopReason") != "end_turn":
            raise ValueError("Gemini 未完成本轮：" + str(result.get("stopReason")))
        answer = "".join(chunks).strip()
        if not answer:
            raise ValueError("Gemini 未返回正文")
        if schema:
            if answer.startswith("```") and answer.endswith("```"):
                answer = answer.partition("\n")[2][:-3].strip()
            answer = json.dumps(json.loads(answer), ensure_ascii=False)
        raw = result.get("usage") or {}
        for field, key in (("inputTokens", "input"), ("outputTokens", "output"), ("totalTokens", "total"),
                           ("cachedReadTokens", "cached"), ("thoughtTokens", "thinking")):
            if type(raw.get(field)) is int:
                usage[key] = raw[field]
        return answer, usage
    finally:
        if proc.returncode is None:
            stop_process(proc)
            try:
                await asyncio.wait_for(proc.wait(), 3)
            except asyncio.TimeoutError:
                stop_process(proc, force=True)
                await proc.wait()
