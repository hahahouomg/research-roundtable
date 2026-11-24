"""Headless clients. Each call starts a new conversation under the CLI's own login."""
import asyncio
import json
import os
import platform
import shutil
import signal
import subprocess
import tempfile
import re
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENTS = ("codex", "gemini")
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
    name = {"codex": "codex", "gemini": "agy"}[agent]
    override = os.environ.get("ROUNDTABLE_" + name.upper() + "_BIN")
    if override:
        return shutil.which(os.path.expanduser(override))
    local = HERE / ".tools" / (platform.system() + "-" + platform.machine()) / name
    shell = shutil.which(name) or shutil.which(str(local)) or shutil.which(str(Path.home() / ".local/bin" / name))
    if agent == "codex" and platform.system() == "Darwin":
        for app in ("ChatGPT", "Codex"):
            bundled = shutil.which(f"/Applications/{app}.app/Contents/Resources/codex-cli/bin/codex")
            if bundled:
                return newer_codex(shell, bundled) if shell else bundled
    return shell


def model(agent):
    default = "gemini-4-neon-medium" if agent == "gemini" else ""
    return os.environ.get("ROUNDTABLE_" + agent.upper() + "_MODEL", default)


def catalog(agent):
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
        options = [m["slug"] for m in json.loads(result.stdout)["models"]
                   if m.get("visibility") == "list"]
    else:
        options = [line.split()[0] for line in result.stdout.splitlines() if line.strip().startswith("gemini-")]
    if not options:
        raise ValueError(f"{agent} CLI 未返回可选型号")
    return list(dict.fromkeys(options))


def counts(data, names):
    return {key: data.get(field) if type(data.get(field)) is int else None for key, field in names.items()}


def parse_reply(backend, output):
    if backend == "gemini":
        try:
            result = json.loads(output)
        except json.JSONDecodeError:
            result = None
        if not isinstance(result, dict) or "status" not in result:
            events = (json.loads(line) for line in output.splitlines() if line.strip())
            result = next((e["result"] for e in events if e.get("event") == "result"), {})
        if result.get("status") != "SUCCESS":
            raise ValueError(result.get("error") or "Gemini 缺少成功回执")
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


async def invoke(agent, prompt, workspace=None, ballot=False, selected_model=None, on_text=None):
    if selected_model is None:
        selected_model = model(agent)
    exe = binary(agent)
    if not exe:
        raise ValueError(f"找不到 {agent} CLI（Gemini 使用 agy），请先运行 status")
    timeout = int(os.environ.get("ROUNDTABLE_TIMEOUT", "1200" if workspace else "300"))
    if timeout <= 0:
        raise ValueError("ROUNDTABLE_TIMEOUT 需要为正整数秒")
    with tempfile.TemporaryDirectory(prefix="roundtable-") as tmp:
        if agent == "codex":
            args = [exe, "-a", "never", "exec", "--ignore-user-config", "--ephemeral",
                    "--disable", "apps", "--disable", "multi_agent", "--json", "--skip-git-repo-check",
                    "--sandbox", "workspace-write" if workspace else "read-only"]
            if not workspace:
                args += ["--disable", "shell_tool"]
            if selected_model:
                args += ["--model", selected_model]
            if ballot:
                schema = Path(tmp) / "vote.json"
                schema.write_text(json.dumps(BALLOT))
                args += ["--output-schema", str(schema)]
            args.append("-")
            payload = prompt
        else:
            settings = {"toolPermission": "strict", "allowNonWorkspaceAccess": False, "agentMode": ""}
            args = [exe, "--input-format", "stream-json", "--output-format", "stream-json", "--sandbox",
                    "--disable-slash-commands", "--model", selected_model, "--settings", json.dumps(settings)]
            if ballot:
                args += ["--json-schema", json.dumps(BALLOT)]
            payload = json.dumps({"event": "user", "message": {"content": prompt}}) + "\n"
        launch = asyncio.create_task(asyncio.create_subprocess_exec(*args, cwd=workspace or tmp, start_new_session=True,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    limit=16 * 1024 * 1024))
        try:
            proc = await asyncio.shield(launch)
            raw, err = await asyncio.wait_for(stream_result(proc, agent, payload, on_text), timeout)
        except BaseException:
            if not launch.done() or (not launch.cancelled() and launch.exception() is None):
                proc = await launch
                if proc.returncode is None:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    except PermissionError:
                        proc.kill()
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
