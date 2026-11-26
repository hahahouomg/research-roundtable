"""Read provider-reported account windows using authenticated local CLI interfaces."""
import asyncio
import json
import os
import select
import shlex
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from providers import MODEL_SEATS, binary, check_claude, guarded_claude_reply
from projects import data_dir
from runtime import PROCESS_GROUP, stop_process


def codex_windows(result):
    main = result.get("rateLimits") or {}
    buckets = result.get("rateLimitsByLimitId") or {main.get("limitId") or "codex": main}
    rows = []
    for bucket, info in buckets.items():
        for period in ("primary", "secondary"):
            w = info.get(period) or {}
            if w.get("usedPercent") is None:
                continue
            mins = w.get("windowDurationMins")
            window = {300: "5 小时", 10080: "每周"}.get(mins, f"{mins} 分钟" if mins else period)
            rows.append(dict(label=f"{info.get('limitName') or bucket} · {window}",
                             percent=100 - w["usedPercent"], reset=w.get("resetsAt")))
    if not rows:
        raise ValueError("该登录方式未返回订阅窗口")
    return dict(plan=main.get("planType"), windows=rows)


async def read_codex(exe):
    proc = await asyncio.create_subprocess_exec(exe, "app-server", "--listen", "stdio://",
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=subprocess.DEVNULL)
    async def send(msg):
        proc.stdin.write((json.dumps(msg) + "\n").encode())
        await proc.stdin.drain()
    async def request(i, method, params):
        await send(dict(id=i, method=method, params=params))
        while True:
            line = await proc.stdout.readline()
            if not line:
                raise ValueError("Codex 额度接口提前退出")
            reply = json.loads(line)
            if reply.get("id") == i:
                if "error" in reply:
                    raise ValueError("Codex 未返回账号额度，请检查 CLI 登录状态")
                return reply["result"]
    try:
        await request(1, "initialize", {"clientInfo": {"name":"roundtable","version":"1.0"}})
        await send({"method":"initialized"})
        return codex_windows(await request(2, "account/rateLimits/read", {}))
    finally:
        proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), 2)
        except asyncio.TimeoutError:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()


def save_statusline(target):
    obj = json.load(sys.stdin)
    buckets = obj.get("quota") or {}
    rows = []
    for bucket, quota in buckets.items():
        if not isinstance(quota, dict):
            continue
        fraction = quota.get("remaining_fraction")
        amount = quota.get("remaining_amount")
        if fraction is None and amount is None:
            continue
        rows.append(dict(label=bucket, percent=round(100 * fraction, 2) if fraction is not None else None,
                         amount=amount, reset=quota.get("reset_time"), disabled=bool(quota.get("disabled"))))
    if rows:
        staging = target.with_suffix(".tmp")
        staging.write_text(json.dumps(dict(plan=obj.get("plan_tier"), windows=rows)))
        staging.replace(target)
    print("Roundtable")


def read_gemini(exe):
    if os.name == "nt":
        raise ValueError("Windows 上请在 agy 终端输入 /usage 查看订阅额度")
    import fcntl
    import pty
    import termios
    # A per-invocation status line gives the same quota buckets shown by /usage.
    # agy associates implicit projects with its cwd; reuse one empty directory.
    workspace = data_dir() / "quota-workspace"
    workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="roundtable-quota-") as tmp:
        target = Path(tmp) / "quota.json"
        command = shlex.join([sys.executable, "-B", str(Path(__file__).resolve()), str(target)])
        settings = {"trustedWorkspaces":[str(workspace)], "statusLine":{"type":"command","enabled":True,"command":command}}
        master, slave = pty.openpty()
        try:
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
            proc = subprocess.Popen([exe, "--log-file", str(Path(tmp) / "agy.log"), "--settings", json.dumps(settings)], cwd=workspace, start_new_session=True,
                                    stdin=slave, stdout=slave, stderr=slave, env={**os.environ, "TERM":"xterm-256color"})
        except BaseException:
            os.close(master)
            raise
        finally:
            os.close(slave)
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if target.exists():
                    return json.loads(target.read_text())
                if proc.poll() is not None:
                    break
                if select.select([master], [], [], 0.15)[0]:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    for query, answer in [(b"\x1b[6n", b"\x1b[1;1R"), (b"\x1b[c", b"\x1b[?1;2c"),
                                          (b"\x1b]11;?", b"\x1b]11;rgb:0000/0000/0000\x07")]:
                        if query in chunk:
                            os.write(master, answer)
            raise ValueError("Gemini 未返回订阅窗口，可在 agy 的 /usage 中核对")
        finally:
            os.close(master)
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def claude_windows(output):
    for line in output.splitlines():
        event = json.loads(line)
        response = event.get("response") or {}
        if event.get("type") != "control_response" or response.get("request_id") != "quota":
            continue
        result = response.get("response") or {}
        limits = result.get("rate_limits") or {}
        rows = []
        for key, label in (("five_hour", "5 小时"), ("seven_day", "7 天"),
                           ("seven_day_opus", "Opus · 7 天"), ("seven_day_sonnet", "Sonnet · 7 天")):
            window = limits.get(key) or {}
            used = window.get("utilization")
            if type(used) in (int, float):
                rows.append(dict(label=label, percent=100 - used, reset=window.get("resets_at")))
        if rows:
            return dict(plan=result.get("subscription_type"), windows=rows)
    raise ValueError("Claude CLI 未返回此账号的订阅窗口，可在 CLI 的 /usage 核对")


async def read_claude(exe, check_access=None):
    if check_access:
        check_access()
    await asyncio.to_thread(check_claude)
    if check_access:
        check_access()
    packet = {"type":"control_request", "request_id":"quota", "request":{"subtype":"get_usage", "skip_behaviors":True}}
    with tempfile.TemporaryDirectory(prefix="roundtable-quota-") as tmp:
        proc = await asyncio.create_subprocess_exec(exe, "-p", "--input-format", "stream-json", "--output-format",
                    "stream-json", "--verbose", "--no-session-persistence", "--strict-mcp-config", "--tools", "",
                    cwd=tmp, **PROCESS_GROUP, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            raw, _ = await asyncio.wait_for(guarded_claude_reply(proc.communicate((json.dumps(packet)+"\n").encode()), check_access), 25)
            return claude_windows(raw)
        except asyncio.TimeoutError as exc:
            raise ValueError("Claude 账号额度查询超时") from exc
        finally:
            stop_process(proc, force=True)
            await proc.wait()


def read_quota(agent, check_access=None):
    if agent not in MODEL_SEATS:
        raise ValueError("此席位尚无订阅额度接口")
    exe = binary(agent)
    if not exe:
        raise ValueError("找不到对应的 CLI")
    if agent == "codex":
        try:
            result = asyncio.run(asyncio.wait_for(read_codex(exe), 20))
        except asyncio.TimeoutError as exc:
            raise ValueError("Codex 账号额度查询超时") from exc
    elif agent == "claude":
        result = asyncio.run(read_claude(exe, check_access))
    else:
        result = read_gemini(exe)
    return {**result, "checked": time.time()}


if __name__ == "__main__":
    save_statusline(Path(sys.argv[1]))
