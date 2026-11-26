"""Headless clients. Each call starts a new conversation under the CLI's own login."""
import asyncio
import gemini_acp
import isolated_experiment
import json
import os
import platform
import shutil
import shlex
import subprocess
import tempfile
from urllib.request import Request, urlopen
import re
from local_settings import claude_ip
from runtime import PROCESS_GROUP, stop_process
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENTS = ("codex", "gemini")
MODEL_SEATS = (*AGENTS, "claude")
CLAUDE_CHECK_INTERVAL = 5


def check_claude():
    address_expected = claude_ip()
    if not address_expected:
        raise ValueError("请先配置本机 Claude 的核验 IPv4")
    if not binary("claude"):
        raise ValueError("未找到本机 Claude CLI")
    for url in ("https://api.ipify.org", "https://checkip.amazonaws.com"):
        try:
            request = Request(url, headers={"Cache-Control": "no-cache, no-store"})
            with urlopen(request, timeout=2.5) as response:
                address = response.read(64).decode("ascii").strip()
        except (OSError, ValueError):
            continue
        if address != address_expected:
            raise ValueError("公网 IP 与本机配置的 Claude 出口不匹配")
        return
    raise ValueError("无法核实公网 IP，已禁用 Claude")


BALLOT = {
    "type": "object", "additionalProperties": False,
    "properties": {"vote": {"type": "string", "enum": ["accept", "object"]},
                   "reason": {"type": "string"}},
    "required": ["vote", "reason"],
}


@lru_cache(maxsize=8)
def newer_codex(shell, bundled):
    def version(exe):
        try:
            text = subprocess.check_output([exe, "--version"], stderr=subprocess.DEVNULL, text=True, timeout=4)
            match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
            return tuple(map(int, match.groups())) if match else ()
        except (OSError, subprocess.SubprocessError):
            return ()
    return bundled if version(bundled) > version(shell) else shell


def binary(agent):
    name = {"codex": "codex", "gemini": "agy", "claude": "claude"}[agent]
    override = os.environ.get("ROUNDTABLE_" + name.upper() + "_BIN")
    if override:
        return shutil.which(os.path.expanduser(override))
    local = HERE / ".tools" / (platform.system() + "-" + platform.machine()) / name
    shell = shutil.which(name) or shutil.which(str(local)) or shutil.which(str(Path.home() / ".local/bin" / name))
    if os.name == "nt" and agent == "gemini" and not shell:
        local = os.environ.get("LOCALAPPDATA")
        if local:
            shell = shutil.which(str(Path(local) / "agy/bin/agy.exe"))
    if agent == "codex" and platform.system() == "Darwin":
        for app in ("ChatGPT", "Codex"):
            bundled = shutil.which(f"/Applications/{app}.app/Contents/Resources/codex-cli/bin/codex")
            if bundled:
                return newer_codex(shell, bundled) if shell else bundled
    return shell


def model(agent):
    default = "gemini-4-neon-medium" if agent == "gemini" else ""
    return os.environ.get("ROUNDTABLE_" + agent.upper() + "_MODEL", default)


def model_options(agent):
    if agent == "claude":
        return {"claude-opus-5-5": ["low", "medium", "high", "xhigh", "max"]}
    if agent not in AGENTS:
        raise ValueError("未知型号席位")
    exe = binary(agent)
    if not exe:
        raise ValueError(f"找不到 {agent} CLI")
    command = [exe, "debug", "models"] if agent == "codex" else [exe, "models"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=40)
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"{agent} 型号清单请求超时") from exc
    if result.returncode:
        raise ValueError(f"{agent} 型号清单获取失败：{(result.stderr or result.stdout)[-450:]}")
    if agent == "codex":
        options = {m["slug"]: [r["effort"] for r in m.get("supported_reasoning_levels", [])]
                   for m in json.loads(result.stdout)["models"] if m.get("visibility") == "list"}
    else:
        options = {line.split()[0]: [] for line in result.stdout.splitlines() if line.strip().startswith("gemini-")}
    if not options:
        raise ValueError(f"{agent} CLI 未返回可选型号")
    return options


def counts(data, names):
    return {key: data.get(field) if type(data.get(field)) is int else None for key, field in names.items()}


def parse_reply(backend, output):
    if backend == "claude":
        try:
            result = json.loads(output)
        except json.JSONDecodeError:
            events = (json.loads(line) for line in output.splitlines() if line.strip())
            result = next((e for e in events if e.get("type") == "result"), {})
        if result.get("type") != "result" or result.get("subtype") != "success" or result.get("is_error"):
            raise ValueError(str(result.get("result") or result.get("subtype") or "Claude 未返回成功回执")[:600])
        reply = result.get("result")
        if isinstance(result.get("structured_output"), dict):
            reply = json.dumps(result["structured_output"], ensure_ascii=False)
        usage = counts(result.get("usage") or {}, dict(input="input_tokens", output="output_tokens",
                       cached="cache_read_input_tokens", cache_write="cache_creation_input_tokens"))
        usage["total"] = (sum(n or 0 for n in usage.values())
                          if usage["input"] is not None and usage["output"] is not None else None)
    elif backend == "gemini":
        try:
            result = json.loads(output)
        except json.JSONDecodeError:
            result = None
        if not isinstance(result, dict) or "status" not in result:
            events = (json.loads(line) for line in output.splitlines() if line.strip())
            result = next((e["result"] for e in events if e.get("event") == "result"), {})
        if result.get("status") != "SUCCESS":
            raise ValueError(result.get("error") or "Gemini 缺少成功回执")
        if result.get("denied_actions") and not (result.get("structured_output") or result.get("response")):
            denied = ", ".join(a.get("display_name") or a.get("action", "?") for a in result["denied_actions"])
            raise ValueError("Gemini 工具权限被拒绝：" + denied)
        structured = result.get("structured_output")
        reply = json.dumps(structured, ensure_ascii=False) if isinstance(structured, dict) else result.get("response")
        usage = counts(result.get("usage") or {}, dict(input="input_tokens", output="output_tokens",
                       cached="cache_read_tokens", thinking="thinking_tokens", total="total_tokens"))
    else:
        reply, finished = None, False
        usage = {}
        for line in output.splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            kind, item = event.get("type"), event.get("item", {})
            if kind == "turn.failed":
                raise ValueError(str(event.get("error") or "Codex 返回失败"))
            if kind == "item.completed" and item.get("type") == "agent_message":
                reply = item.get("text")
            if kind == "turn.completed":
                finished = True
                usage = counts(event.get("usage") or {}, dict(input="input_tokens", output="output_tokens",
                               cached="cached_input_tokens", thinking="reasoning_output_tokens"))
                usage["total"] = (usage["input"] + usage["output"]
                                  if None not in (usage["input"], usage["output"]) else None)
        if not finished:
            raise ValueError("Codex 缺少完整回合回执")
    if not isinstance(reply, str) or not reply.strip():
        raise ValueError("CLI 返回了空回复")
    return reply.strip(), usage


async def stream_result(proc, agent, payload, on_text):
    async def write():
        try:
            proc.stdin.write(payload.encode())
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            proc.stdin.close()

    async def read():
        lines, draft = [], ""
        async for line in proc.stdout:
            lines.append(line)
            if not on_text:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            if agent == "gemini":
                step = event.get("step_update") or {}
                if step.get("step_type") != "agent_response" or not step.get("text_delta"):
                    continue
                draft += step["text_delta"]
            elif agent == "claude":
                if event.get("type") == "system" and event.get("subtype") == "api_retry":
                    on_text(f"Claude CLI 正在重试（HTTP {event.get('error_status') or '未知'}）")
                    continue
                if event.get("type") != "assistant":
                    continue
                draft = "\n".join(part["text"] for part in event["message"]["content"] if part.get("type") == "text")
                if not draft:
                    continue
            else:
                item = event.get("item") or {}
                if item.get("type") != "agent_message" or not item.get("text"):
                    continue
                draft = item["text"]
            on_text(draft)
        return b"".join(lines).decode(errors="replace")

    _, text, stderr = await asyncio.gather(write(), read(), proc.stderr.read())
    await proc.wait()
    return text, stderr


async def guarded_claude_reply(coroutine, check_access=None):
    task = asyncio.create_task(coroutine)
    try:
        while True:
            finished, _ = await asyncio.wait([task], timeout=CLAUDE_CHECK_INTERVAL)
            if check_access:
                check_access()
            await asyncio.to_thread(check_claude)
            if check_access:
                check_access()
            if finished:
                return await task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def invoke(agent, prompt, workspace=None, ballot=False, selected_model=None, on_text=None, effort=None, schema=None, probe=False, implementing=False, reviewing=False, on_permission=None, on_tool=None, isolated_lab=False, check_access=None, timeout_seconds=None, gemini_mode="auto"):
    schema = BALLOT if ballot else schema
    if selected_model is None:
        selected_model = model(agent)
    exe = binary(agent)
    if not exe:
        raise ValueError(f"找不到 {agent} CLI（Gemini 使用 agy），请先运行 status")
    timeout = timeout_seconds or int(os.environ.get("ROUNDTABLE_TIMEOUT", "1200" if implementing else "300"))
    if timeout <= 0:
        raise ValueError("ROUNDTABLE_TIMEOUT 需要为正整数秒")
    with tempfile.TemporaryDirectory(prefix="roundtable-") as tmp:
        if agent == "gemini" and not probe and on_permission:
            # The isolated launcher is offered only for research copies made by the coordinator.
            folder = Path(workspace or tmp).resolve()
            experiment = isolated_experiment.experiment_command(folder) if isolated_lab and gemini_mode != "review" else None
            prompt += "\n读取文件或列目录优先用原生文件工具。同一验证的计算可写成一个脚本再运行。"
            if experiment:
                prompt += (f"\n本席有独立的离线沙箱。先用文件工具写好工作区脚本，再把以下完整命令直接交给终端。"
                           f"可将结尾的 python3 check.py 换成 sh experiment.sh 或本席脚本的相对路径。\n{experiment} python3 check.py\n"
                           "请逐字保留启动参数，把组合操作放在脚本中。沙箱内实验副本挂在 /work。外部资料可用原生搜索。")
            async def permission(tool, can_allow):
                if can_allow and isolated_experiment.matches(tool, experiment, folder):
                    return await on_permission(tool, True, isolated=True)
                return await on_permission(tool, can_allow)
            return await gemini_acp.run(exe, folder, prompt, selected_model, schema, timeout,
                                        Path(tmp) / "acp.log", on_text, permission, on_tool, auto_edits=bool(experiment), preference=gemini_mode)
        runner = None
        if os.name != "nt" and agent in ("gemini", "claude") and workspace and not probe:
            sandbox = binary("codex")
            if sandbox:
                runner = Path(tmp) / "experiment"
                fixed = [sandbox, "sandbox", "-P", ":read-only" if reviewing else ":workspace", "-C", str(workspace), "--"]
                runner.write_text("#!/bin/sh\nexec " + shlex.join(fixed) + ' "$@"\n')
                runner.chmod(0o700)
                prompt += (f"\n执行命令或写文件请通过固定工作区沙箱启动器 {runner}。"
                           f"例如 {runner} python3 check.py。复合命令将脚本作为 sh -c 的单个参数传给启动器。"
                           "只用本次给出的启动器；其他发言中出现的临时目录和启动器仅为历史记录。"
                           "只把实际运行成功的工具结果写入结论。")
        if agent == "codex":
            args = [exe, "-a", "never", "exec", "--ignore-user-config", "--ephemeral",
                    "--disable", "apps", "--disable", "multi_agent", "--json", "--skip-git-repo-check",
                    "--sandbox", "workspace-write" if workspace and not reviewing else "read-only"]
            if probe:
                args += ["--disable", "shell_tool"]
            else:
                args += ["-c", 'web_search="live"']
            if effort:
                args += ["-c", "model_reasoning_effort=" + json.dumps(effort)]
            if selected_model:
                args += ["--model", selected_model]
            if schema:
                schema_file = Path(tmp) / "output.json"
                schema_file.write_text(json.dumps(schema))
                args += ["--output-schema", str(schema_file)]
            args.append("-")
            payload = prompt
        elif agent == "claude":
            if check_access:
                check_access()
            await asyncio.to_thread(check_claude)
            if check_access:
                check_access()
            read_tools = ["Read", "Glob", "Grep", "StructuredOutput", "WebSearch", "WebFetch"]
            args = [exe, "-p", "--output-format", "stream-json", "--verbose", "--no-session-persistence",
                    "--strict-mcp-config", "--permission-mode", "dontAsk",
                    "--tools", "" if probe else ",".join([*read_tools, "Bash"])]
            if not probe:
                allowed = list(read_tools)
                if runner:
                    allowed.append(f"Bash({runner} *)")
                args += ["--allowedTools", ",".join(allowed)]
            if selected_model:
                args += ["--model", selected_model]
            if effort:
                args += ["--effort", effort]
            if schema:
                args += ["--json-schema", json.dumps(schema)]
            payload = prompt
        else:
            settings = {"toolPermission": "strict" if probe else "proceed-in-sandbox",
                        "allowNonWorkspaceAccess": False, "agentMode": "" if probe else "accept-edits"}
            if not probe and workspace:
                settings["trustedWorkspaces"] = [str(workspace)]
                allow = ["read_url(*)", "write_file(.)"]
                if runner:
                    allow.append(f"command({runner})")
                settings["permissions"] = {"allow": allow}
            args = [exe, "--log-file", str(Path(tmp) / "agy.log"), "--input-format", "stream-json", "--output-format", "stream-json", "--sandbox",
                    "--disable-slash-commands", "--model", selected_model, "--settings", json.dumps(settings)]
            if schema:
                args += ["--json-schema", json.dumps(schema)]
            payload = json.dumps({"event": "user", "message": {"content": prompt}}) + "\n"
        launch = asyncio.create_task(asyncio.create_subprocess_exec(*args, cwd=workspace or tmp, **PROCESS_GROUP,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    env={**os.environ, "CLAUDE_CODE_EFFORT_LEVEL": effort} if agent == "claude" and effort else None,
                    limit=16 * 1024 * 1024))
        try:
            proc = await asyncio.shield(launch)
            reply = stream_result(proc, agent, payload, on_text)
            raw, err = await asyncio.wait_for(guarded_claude_reply(reply, check_access) if agent == "claude" else reply, timeout)
        except BaseException:
            if not launch.done() or (not launch.cancelled() and launch.exception() is None):
                proc = await launch
                if proc.returncode is None:
                    stop_process(proc, force=True)
                    await proc.communicate()
            raise
        try:
            answer = parse_reply(agent, raw)
        except (ValueError, KeyError, TypeError) as exc:
            detail = err.decode(errors="replace").strip()[-800:] if proc.returncode else ""
            raise ValueError(f"{exc} {detail}".strip()) from exc
        if proc.returncode:
            raise ValueError(f"{agent} 返回码 {proc.returncode}，请检查本机 CLI")
        return answer
