"""Configuration written only to this installation's data directory."""
from ipaddress import IPv4Address
import os
from pathlib import Path

from runtime import write_text


def data_dir():
    return Path(os.environ.get("ROUNDTABLE_HOME", Path(__file__).resolve().parent / "data")).expanduser().resolve()


def claude_ip():
    path = data_dir() / "claude-ip"
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def set_claude_ip(value):
    address = value.strip()
    if not address:
        (data_dir() / "claude-ip").unlink(missing_ok=True)
        return
    try:
        address = str(IPv4Address(address))
    except ValueError as exc:
        raise ValueError("请输入有效的 IPv4 地址，例如 203.0.113.10") from exc
    data_dir().mkdir(parents=True, mode=0o700, exist_ok=True)
    write_text(data_dir() / "claude-ip", address + "\n")
