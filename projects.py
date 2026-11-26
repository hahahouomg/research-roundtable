"""Project workspaces and their model preferences, stored alongside discussion history."""
from pathlib import Path

from local_settings import claude_ip, data_dir, set_claude_ip
from record_store import project_folder
from providers import AGENTS, MODEL_SEATS, model, model_options, check_claude

DEFAULT = "默认"
PROJECT_HELP = "project list | project add 名称 [目录] | project use 名称 | project path 目录"
MODEL_HELP = "model | model 席位 | model list 席位 | model set 席位 型号或default [思考强度] | model claude on/off | model claude ip IPv4"


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
            ("projects", "codex_effort", "TEXT"),
            ("projects", "gemini_auto_lab", "INTEGER NOT NULL DEFAULT 0"),
            ("projects", "gemini_mode", "TEXT NOT NULL DEFAULT 'auto'"),
            ("projects", "call_minutes", "INTEGER"),
            ("projects", "claude", "TEXT"),
            ("projects", "claude_effort", "TEXT"),
            ("projects", "claude_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ("projects", "claude_epoch", "INTEGER NOT NULL DEFAULT 0"),
            ("sessions", "folder_ready", "INTEGER NOT NULL DEFAULT 0"),
            ("sessions", "failure", "TEXT"),
            ("sessions", "settings", "TEXT"),
            ("sessions", "assignments", "TEXT"),
            ("calls", "effort", "TEXT"),
            ("calls", "owner", "INTEGER"),
            ("projects", "trashed", "INTEGER DEFAULT 0"),
            ("sessions", "trash_root", "TEXT"),
            ("sessions", "stop_requested", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if column not in {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        # Expose records archived in earlier releases without deleting their contents.
        if db.execute("PRAGMA user_version").fetchone()[0] == 0:
            db.execute("UPDATE projects SET trashed=0 WHERE trashed=1")
            db.execute("UPDATE sessions SET trash_root=NULL WHERE trash_root IS NOT NULL")
            db.execute("DROP TRIGGER IF EXISTS guard_session_insert")
            db.execute("PRAGMA user_version=1")
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


def claude_access(db, project):
    """A later off/on cycle must not revive a call that the user switched off."""
    epoch = project_row(db, project)["claude_epoch"]
    address = claude_ip()

    def check():
        row = db.execute("SELECT claude_enabled,claude_epoch FROM projects WHERE name=? AND trashed=0",
                         (project,)).fetchone()
        if address != claude_ip():
            raise ValueError("Claude 的出口配置已修改，请重新启动调用")
        if not row or not row["claude_enabled"] or row["claude_epoch"] != epoch:
            raise ValueError("当前项目已关闭此轮 Claude 调用")
    return check


def models_for(row):
    models = {agent: row[agent] or model(agent) for agent in AGENTS}
    if row["claude_enabled"]:
        models["claude"] = row["claude"] or model("claude")
    return models


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
        binding = str(Path(parts[1]).expanduser().resolve()) if len(parts) == 2 else str(Path("workspaces") / project_folder(name).name)
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


def configure_claude_ip(db, address):
    set_claude_ip(address)
    if not claude_ip():
        db.execute("UPDATE projects SET claude_enabled=0,claude_epoch=claude_epoch+1 WHERE claude_enabled=1")


def model_command(db, current, args, interactive=False):
    row = project_row(db, current)
    chosen = models_for(row)
    if not args:
        print("项目  " + current)
        for agent in chosen:
            effort = row[agent + "_effort"] if agent in ("codex", "claude") else None
            print(f"  {agent:<7} {chosen.get(agent) or 'CLI 默认'} {effort or ''}".rstrip())
        print(MODEL_HELP)
        return
    if len(args) == 3 and args[:2] == ["claude", "ip"]:
        configure_claude_ip(db, "" if args[2] == "off" else args[2])
        return
    if args in (["claude", "on"], ["claude", "off"]):
        if args[-1] == "on":
            check_claude()
            if not db.execute("UPDATE projects SET claude_enabled=1 WHERE name=? AND claude_epoch=?",
                              (current, row["claude_epoch"])).rowcount:
                raise ValueError("检查期间 Claude 已被关闭")
        else:
            db.execute("UPDATE projects SET claude_enabled=0,claude_epoch=claude_epoch+1 WHERE name=?", (current,))
        return
    pick = len(args) == 1 and args[0] in MODEL_SEATS
    list_only = len(args) == 2 and args[0] == "list" and args[1] in MODEL_SEATS
    if pick or list_only:
        agent = args[-1]
        info = model_options(agent)
        options = list(info)
        print(f"{agent}  ·  当前 {chosen.get(agent) or 'CLI 默认'}\n  0  恢复默认")
        for i, option in enumerate(options, 1):
            mark = " *" if option == chosen.get(agent) else ""
            print(f"  {i:2}  {option}{mark}  {' / '.join(info[option])}".rstrip())
        if list_only or not interactive:
            return
        response = input("选择编号（回车取消） > ").strip()
        if not response:
            return
        if not response.isdecimal() or int(response) > len(options):
            raise ValueError("编号不在清单中")
        args = ["set", agent, (["default"] + options)[int(response)]]
        if agent in ("codex", "claude") and args[-1] != "default" and info[args[-1]]:
            available = info[args[-1]]
            level = input("思考强度（" + "/".join(available) + "，回车使用默认） > ").strip()
            if level:
                args.append(level)
    effort = None
    if len(args) == 4 and args[0] == "set" and args[1] in ("codex", "claude"):
        choice, effort = args[2:]
        if effort == "default":
            effort = None
        elif effort not in model_options(args[1]).get(choice, []):
            raise ValueError("请为选定型号选择 CLI 支持的思考强度")
        args = args[:3]
    if len(args) != 3 or args[0] != "set" or args[1] not in MODEL_SEATS:
        raise ValueError(MODEL_HELP)
    _, agent, choice = args
    if not choice or any(c.isspace() for c in choice) or choice.startswith("-"):
        raise ValueError("请使用模型清单里的型号 ID")
    if agent == "gemini" and choice != "default" and not choice.startswith("gemini-"):
        raise ValueError("Gemini 席位需要 gemini- 开头的型号，可用 model list gemini 查看")
    value = None if choice == "default" else choice
    if agent in ("codex", "claude"):
        db.execute(f"UPDATE projects SET {agent}=?,{agent}_effort=? WHERE name=?", (value, effort, current))
    else:
        db.execute("UPDATE projects SET gemini=? WHERE name=?", (value, current))
    effective = project_row(db, current)[agent] or model(agent)
    print(f"已保存  {current} · {agent} · {effective or 'CLI 默认'}")
