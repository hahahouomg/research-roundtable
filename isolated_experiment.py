"""Give disposable Linux research copies a no-network terminal for agy experiments."""
from functools import lru_cache
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import re


@lru_cache(maxsize=1)
def sandbox():
    exe = "/usr/bin/bwrap"
    if not sys.platform.startswith("linux") or not os.access(exe, os.X_OK):
        return ()
    args = [exe, "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL",
            "--clearenv", "--ro-bind", "/usr", "/usr"]
    for name in ("bin", "sbin", "lib", "lib64"):
        path = Path("/") / name
        if path.is_symlink():
            args += ["--symlink", os.readlink(path), str(path)]
        elif path.is_dir():
            args += ["--ro-bind", str(path), str(path)]
    # Fontconfig needs its system configuration to resolve CJK fonts for reports.
    if Path("/etc/fonts").is_dir():
        args += ["--ro-bind", "/etc/fonts", "/etc/fonts"]
    runtime = Path(sys.prefix)
    for name in ("bin", "lib"):
        if (runtime / name).is_dir():
            args += ["--ro-bind", str(runtime / name), "/runtime/" + name]
    args += ["--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--setenv", "HOME", "/tmp",
             "--setenv", "PATH", "/runtime/bin:/usr/bin:/bin", "--setenv", "LANG", "C.UTF-8"]
    try:
        if subprocess.run([*args, "--", "/bin/true"], capture_output=True, timeout=5).returncode == 0:
            return tuple(args)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ()


def experiment_command(folder):
    if not sandbox():
        return None
    # Leave explicit user/administrator command restrictions to agy's normal approval UI.
    authority = Path.home() / ".gemini/antigravity-cli/settings.json"
    if Path("/etc/antigravity/admin_settings.json").exists():
        return None
    try:
        current = json.loads(authority.read_text()) if authority.is_file() else {}
    except (ValueError, OSError):
        return None
    rules = current.get("permissions") or {}
    if (current.get("toolPermission") in ("strict", "request-review")
            or any(r.startswith(("command(", "unsandboxed(")) for scope in ("ask", "deny") for r in rules.get(scope, []))):
        return None
    return shlex.join([*sandbox(), "--bind", str(folder), "/work", "--chdir", "/work", "--"])


def matches(tool, prefix, folder):
    data = tool.get("rawInput") or {}
    if (not prefix or tool.get("name") != "run_command" or tool.get("kind") != "execute" or not isinstance(data, dict)
            or set(data) - {"CommandLine", "WaitMsBeforeAsync", "toolSummary", "Cwd"}
            or data.get("Cwd", str(folder)) != str(folder)):
        return False
    # Match the entire host command. Only an interpreter and one literal script path
    # may follow the fixed launcher. All shell composition belongs inside the sandbox.
    if not isinstance(data.get("CommandLine"), str):
        return False
    other = tool.get("args") or {}
    if not isinstance(other, dict) or ("CommandLine" in other and other["CommandLine"] != data["CommandLine"]):
        return False
    script = r"[\w.][\w./-]*"
    return bool(re.fullmatch(re.escape(prefix) + r" (?:python3 |sh |bash )" + script,
                             data.get("CommandLine") or ""))
