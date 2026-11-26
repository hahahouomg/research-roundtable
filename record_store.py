"""Locate discussion artifacts and reconcile filesystem cleanup with the local index."""
import hashlib
import re
import shutil

from local_settings import data_dir


def project_folder(project):
    slug = re.sub(r'[^\w.-]+', '-', project).strip('.-')[:40]
    identity = hashlib.sha256(project.encode()).hexdigest()[:16]
    return data_dir() / "projects" / f"{slug or 'project'}-{identity}"


def discussion_folder(project, sid):
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", sid):
        raise ValueError("无效的讨论编号")
    return project_folder(project) / "discussions" / sid


def reconcile(db, save):
    rows = db.execute("SELECT id,project,folder_ready,state FROM sessions").fetchall()
    changes = []
    for row in rows:
        location = discussion_folder(row["project"], row["id"])
        if not row["folder_ready"] or not location.is_dir():
            changes.append((row["id"], row["project"], location))
    if not changes:
        return
    db.execute("BEGIN IMMEDIATE")
    try:
        for sid, project, location in changes:
            row = db.execute("SELECT folder_ready,state FROM sessions WHERE id=?", (sid,)).fetchone()
            if not row:
                continue
            busy = row["state"] in ("active", "implementing") or db.execute(
                "SELECT 1 FROM calls WHERE session=? AND ended IS NULL LIMIT 1", (sid,)).fetchone()
            if not row["folder_ready"]:
                location.mkdir(mode=0o700, parents=True, exist_ok=True)
                old = data_dir() / "exports" / sid
                if old.is_dir() and not busy:
                    for item in old.iterdir():
                        name = "排版源稿.html.txt" if item.name == "方案.html" else item.name
                        if not (location / name).exists():
                            shutil.move(str(item), str(location / name))
                        elif item.is_file() and item.read_bytes() == (location / name).read_bytes():
                            item.unlink()
                    if not any(old.iterdir()):
                        old.rmdir()
                elif busy:
                    continue
                save(db, sid, project)
                db.execute("UPDATE sessions SET folder_ready=1 WHERE id=?", (sid,))
            elif not location.is_dir():
                if busy:
                    db.execute("UPDATE sessions SET stop_requested=1 WHERE id=?", (sid,))
                    continue
                db.execute("DELETE FROM tool_permissions WHERE call_id IN (SELECT id FROM calls WHERE session=?)", (sid,))
                db.execute("DELETE FROM calls WHERE session=?", (sid,))
                db.execute("UPDATE sessions SET parent=NULL WHERE parent=?", (sid,))
                db.execute("DELETE FROM sessions WHERE id=?", (sid,))
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
