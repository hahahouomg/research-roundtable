"""Project workspaces and their model preferences, stored alongside discussion history."""
import os
from pathlib import Path

from providers import AGENTS, catalog, model

DEFAULT = "默认"
PROJECT_HELP = "project list | project add 名称 [目录] | project use 名称 | project path 目录"
MODEL_HELP = "model | model codex | model gemini | model list 席位 | model set 席位 型号或default"


def data_dir():
    return Path(os.environ.get("ROUNDTABLE_HOME", Path(__file__).resolve().parent / "data")).expanduser().resolve()


def setup(db):
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS projects(
            name TEXT PRIMARY KEY, workspace TEXT, codex TEXT, gemini TEXT)""")
        db.execute("INSERT OR IGNORE INTO projects(name) VALUES(?)", (DEFAULT,))
        db.execute("CREATE TABLE IF NOT EXISTS selection(id INTEGER PRIMARY KEY, project TEXT NOT NULL)")
        db.execute("INSERT OR IGNORE INTO selection VALUES(1,?)", (DEFAULT,))
        if "project" not in {r["name"] for r in db.execute("PRAGMA table_info(sessions)")}:
            db.execute("ALTER TABLE sessions ADD COLUMN project TEXT NOT NULL DEFAULT '默认'")
        if "model" not in {r["name"] for r in db.execute("PRAGMA table_info(calls)")}:
            db.execute("ALTER TABLE calls ADD COLUMN model TEXT")
        for table, column, definition in (
            ("projects", "trashed", "INTEGER DEFAULT 0"),
            ("sessions", "trash_root", "TEXT"),
            ("sessions", "stop_requested", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if column not in {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        db.execute("""CREATE TRIGGER IF NOT EXISTS guard_session_insert BEFORE INSERT ON sessions
                    WHEN EXISTS(SELECT 1 FROM projects WHERE name=NEW.project AND trashed=1)
                      OR EXISTS(SELECT 1 FROM sessions WHERE id=NEW.parent AND trash_root IS NOT NULL)
                    BEGIN SELECT RAISE(ABORT,'该项目或讨论已移入回收站'); END""")
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise


def project_row(db, name=None):
    if name is None:
        name, = db.execute("SELECT project FROM selection WHERE id=1").fetchone()
    row = db.execute("SELECT * FROM projects WHERE name=? AND trashed=0", (name,)).fetchone()
    if row is None:
        raise ValueError(f"找不到项目「{name}」，请用 project list 查看")
    return row


def workspace(row):
    if row["workspace"]:
        return data_dir() / row["workspace"]  # Absolute bindings override the base.
    return None


def models_for(row):
    return {agent: row[agent] or model(agent) for agent in AGENTS}


def project_command(db, current, args, interactive=False):
    if not args or args == ["list"]:
        rows = db.execute("""SELECT p.*, COUNT(s.id) AS n FROM projects p
                              LEFT JOIN sessions s ON s.project=p.name AND s.trash_root IS NULL WHERE p.trashed=0 GROUP BY p.name ORDER BY p.name""").fetchall()
        for number, row in enumerate(rows, 1):
            print(f"{number:2}  {'*' if row['name'] == current else ' '} {row['name']}  ·  {row['n']} 条记录  ·  "
                  f"{workspace(row) or '未绑定目录'}")
        print(PROJECT_HELP)
        if args or not interactive:
            return current
        choice = input("切换项目编号（回车保留） > ").strip()
        if not choice:
            return current
        if not choice.isdecimal() or not 1 <= int(choice) <= len(rows):
            raise ValueError("编号不在清单中")
        args = ["use", rows[int(choice) - 1]["name"]]
    op, *parts = args
    if op == "use" and len(parts) == 1:
        current = parts[0]
        changed = db.execute("""UPDATE selection SET project=? WHERE id=1 AND EXISTS(
                             SELECT 1 FROM projects WHERE name=? AND trashed=0)""", (current, current)).rowcount
        if not changed:
            raise ValueError(f"找不到项目「{current}」，请用 project list 查看")
    elif op == "add" and 1 <= len(parts) <= 2:
        name = parts[0].strip()
        if not name or name in (".", "..") or "/" in name or not name.isprintable():
            raise ValueError("请输入单行项目名，目录作为第二个参数")
        binding = str(Path(parts[1]).expanduser().resolve()) if len(parts) == 2 else str(Path("workspaces") / name)
        db.execute("BEGIN IMMEDIATE")
        try:
            if db.execute("SELECT 1 FROM projects WHERE name=?", (name,)).fetchone():
                raise ValueError(f"项目「{name}」已存在，可用 project use 切换")
            (data_dir() / binding).mkdir(parents=True, exist_ok=True)
            db.execute("INSERT INTO projects(name,workspace) VALUES(?,?)", (name, binding))
            db.execute("UPDATE selection SET project=? WHERE id=1", (name,))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        current = name
    elif op == "path" and len(parts) == 1:
        target = Path(parts[0]).expanduser().resolve()
        if not target.is_dir():
            raise ValueError("重新绑定时请指定已存在的目录")
        db.execute("UPDATE projects SET workspace=? WHERE name=?", (str(target), current))
    else:
        raise ValueError(PROJECT_HELP)
    print(f"当前项目  {current}  ·  {workspace(project_row(db, current)) or '未绑定目录'}")
    return current


def model_command(db, current, args, interactive=False):
    chosen = models_for(project_row(db, current))
    if not args:
        print("项目  " + current)
        for agent in AGENTS:
            print(f"  {agent:<7} {chosen[agent] or 'CLI 默认'}")
        print(MODEL_HELP)
        return
    pick = len(args) == 1 and args[0] in AGENTS
    list_only = len(args) == 2 and args[0] == "list" and args[1] in AGENTS
    if pick or list_only:
        agent = args[-1]
        options = catalog(agent)
        print(f"{agent}  ·  当前 {chosen[agent] or 'CLI 默认'}\n  0  恢复默认")
        for i, option in enumerate(options, 1):
            mark = " *" if option == chosen[agent] else ""
            print(f"  {i:2}  {option}{mark}")
        if list_only or not interactive:
            return
        response = input("选择编号（回车取消） > ").strip()
        if not response:
            return
        if not response.isdecimal() or int(response) > len(options):
            raise ValueError("编号不在清单中")
        args = ["set", agent, (["default"] + options)[int(response)]]
    if len(args) != 3 or args[0] != "set" or args[1] not in AGENTS:
        raise ValueError(MODEL_HELP)
    _, agent, choice = args
    if not choice or any(c.isspace() for c in choice) or choice.startswith("-"):
        raise ValueError("请使用模型清单里的型号 ID")
    if agent == "gemini" and choice != "default" and not choice.startswith("gemini-"):
        raise ValueError("Gemini 席位需要 gemini- 开头的型号，可用 model list gemini 查看")
    db.execute(f"UPDATE projects SET {agent}=? WHERE name=?", (None if choice == "default" else choice, current))
    effective = models_for(project_row(db, current))[agent]
    print(f"已保存  {current} · {agent} · {effective or 'CLI 默认'}")


def move_trash(db, project, kind, item, restore):
    """Only change ledger metadata. User workspaces never participate in this transaction."""
    db.execute("BEGIN IMMEDIATE")
    try:
        if kind == "project":
            if item == DEFAULT:
                raise ValueError("默认项目中的讨论可以单独移除")
            if not restore and item != project:
                raise ValueError("请打开要移除的项目")
            if not restore and db.execute("SELECT 1 FROM sessions WHERE project=? AND state IN ('active','implementing')",
                                         (item,)).fetchone():
                raise ValueError("请先停止或等待项目中正在进行的任务")
            count = db.execute("UPDATE projects SET trashed=? WHERE name=? AND trashed=?",
                               (0 if restore else 1, item, 1 if restore else 0)).rowcount
            if not restore:
                db.execute("UPDATE selection SET project=? WHERE project=?", (DEFAULT, item))
        elif kind == "session":
            if restore:
                row = db.execute("SELECT parent FROM sessions WHERE id=? AND project=? AND trash_root=id",
                                 (item, project)).fetchone()
                if row and db.execute("SELECT 1 FROM sessions WHERE id=? AND trash_root IS NOT NULL", (row[0],)).fetchone():
                    raise ValueError("请先恢复上游讨论")
                count = db.execute("UPDATE sessions SET trash_root=NULL WHERE project=? AND trash_root=?",
                                   (project, item)).rowcount if row else 0
            else:
                branch = """WITH RECURSIVE branch(id) AS (
                    SELECT id FROM sessions WHERE id=? AND project=? AND trash_root IS NULL UNION ALL
                    SELECT s.id FROM sessions s JOIN branch ON s.parent=branch.id WHERE s.project=? AND s.trash_root IS NULL) """
                args = (item, project, project)
                if db.execute(branch + "SELECT 1 FROM sessions WHERE id IN branch AND state IN ('active','implementing')",
                              args).fetchone():
                    raise ValueError("请先停止或等待此讨论及其追问")
                db.execute(branch + "UPDATE sessions SET trash_root=? WHERE id IN branch", (*args, item))
                count, = db.execute("SELECT changes()").fetchone()
        else:
            raise ValueError("未知的回收站操作")
        if not count:
            raise ValueError("记录不存在或状态已改变，请刷新")
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
