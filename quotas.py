"""Read provider-reported account windows using authenticated local CLI interfaces."""
import asyncio
import fcntl
import json
import os
import pty
import select
import shlex
import struct
import subprocess
import sys
import tempfile
import termios
import time
from pathlib import Path

from providers import binary


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
    # A per-invocation status line gives the same quota buckets shown by /usage.
    with tempfile.TemporaryDirectory(prefix="roundtable-quota-") as tmp:
        target = Path(tmp) / "quota.json"
        command = shlex.join([sys.executable, "-B", str(Path(__file__).resolve()), str(target)])
        settings = {"trustedWorkspaces":[tmp], "statusLine":{"type":"command","enabled":True,"command":command}}
        master, slave = pty.openpty()
        try:
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
            proc = subprocess.Popen([exe, "--settings", json.dumps(settings)], cwd=tmp, start_new_session=True,
                                    stdin=slave, stdout=slave, stderr=slave, env={**os.environ, "TERM":"xterm-256color"})
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


def read_quota(agent):
    exe = binary(agent)
    if not exe:
        raise ValueError("找不到对应的 CLI")
    if agent == "codex":
        try:
            result = asyncio.run(asyncio.wait_for(read_codex(exe), 20))
        except asyncio.TimeoutError as exc:
            raise ValueError("Codex 账号额度查询超时") from exc
    else:
        result = read_gemini(exe)
    return {**result, "checked": time.time()}


if __name__ == "__main__":
    save_statusline(Path(sys.argv[1]))
