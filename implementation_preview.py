"""Run an implementation on an isolated baseline and save its actual changes."""
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from research import research_copy

PATCH_NAME = "implementation.patch"


@contextmanager
def implementation_preview(source, patch):
    git = shutil.which("git")
    if not git:
        raise ValueError("生成实施预览需要 Git")
    with tempfile.TemporaryDirectory(prefix="roundtable-implementation-") as tmp:
        temp = Path(tmp)
        work = temp / "work"
        hooks = temp / "hooks"
        hooks.mkdir()
        env = {key: value for key, value in os.environ.items() if key not in (
            "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_PREFIX")}
        env["GIT_OPTIONAL_LOCKS"] = "0"
        def run(directory, *args, check=True):
            result = subprocess.run([git, "-c", f"core.hooksPath={hooks}", "-C", str(directory), *args],
                                    capture_output=True, env=env)
            if check and result.returncode:
                raise ValueError(result.stderr.decode("utf-8", "replace").strip() or "Git 操作失败")
            return result

        root = run(source, "rev-parse", "--show-toplevel", check=False)
        if root.returncode == 0:
            if Path(os.fsdecode(root.stdout.rstrip(b"\r\n"))).resolve() != source:
                raise ValueError("请选择 Git 仓库根目录")
            if run(source, "status", "--porcelain", "--untracked-files=normal").stdout:
                raise ValueError("Git 工作目录有未提交的改动。请提交或暂存后再生成预览。")
            base = run(source, "rev-parse", "HEAD", check=False)
            if base.returncode:
                raise ValueError("Git 仓库至少需要一次提交才能生成预览")
            baseline = base.stdout.decode("ascii").strip()
            run(source, "worktree", "add", "--detach", str(work), baseline)
        else:
            research_copy(source, work)
            run(work, "init", "--quiet")
            run(work, "add", "--force", "--all")
            baseline = run(work, "write-tree").stdout.decode("ascii").strip()

        try:
            yield work
            run(work, "add", "--all")
            diff = run(work, "diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv",
                       "--src-prefix=a/", "--dst-prefix=b/", baseline, "--").stdout
            if diff and patch.parent.is_dir():
                with tempfile.NamedTemporaryFile(dir=patch.parent, delete=False) as file:
                    staged = Path(file.name)
                    try:
                        file.write(diff)
                        file.close()
                        staged.replace(patch)
                    finally:
                        staged.unlink(missing_ok=True)
        finally:
            if root.returncode == 0:
                run(source, "worktree", "remove", "--force", str(work))
