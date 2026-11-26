"""Create private, writable experiment folders from the project's working files."""
import hashlib
import os
import shutil
import stat
import subprocess
from pathlib import Path

from projects import data_dir


def research_copy(source, target):
    target.mkdir()
    if source is None:
        return
    if not source.is_dir():
        raise ValueError(f"绑定目录不可用：{source}")
    # Include uncommitted work while respecting Git's ignore rules.
    # A workspace created inside roundtable/data is ignored by the harness repo.
    # Only its own repository should decide which of its files to copy.
    managed = data_dir() / "workspaces" in source.resolve().parents
    git = shutil.which("git") if not managed or (source / ".git").exists() else None
    tracked = subprocess.run([git, "-C", str(source), "ls-files", "-z", "--cached", "--others",
                              "--exclude-standard", "--", "."], capture_output=True) if git else None
    names = None
    if tracked and tracked.returncode == 0:
        names = {Path(os.fsdecode(name)) for name in tracked.stdout.split(b"\0") if name}
    parents = None if names is None else {parent for path in names for parent in path.parents}
    skip = {".git", ".venv", "node_modules", "__pycache__", ".ssh", ".aws", ".codex", ".claude", ".gemini", ".agents", ".mcp.json"}
    excluded = {target.parent.resolve(), data_dir()}
    def allowed(path):
        return (not path.is_symlink() and not (getattr(path.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
                and path.name not in skip and path not in excluded
                and path.name != ".env" and not path.name.startswith(".env."))
    for root, dirs, files in os.walk(source, onerror=raise_walk_error):
        base = Path(root)
        dirs[:] = [d for d in dirs if allowed(base / d) and
                   (parents is None or (base / d).relative_to(source) in parents)]
        (target / base.relative_to(source)).mkdir(parents=True, exist_ok=True)
        for name in files:
            original = base / name
            relative = original.relative_to(source)
            if names is not None and relative not in names:
                continue
            if allowed(original) and stat.S_ISREG(original.lstat().st_mode):
                dest = target / relative
                shutil.copy2(original, dest)


def raise_walk_error(exc):
    raise exc


def input_fingerprint(folder):
    result = {}
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(128 * 1024), b""):
                    digest.update(chunk)
            result[path.relative_to(folder).as_posix()] = digest.hexdigest()
    return result
