"""Stockage de l'application web : base SQLite + un dossier de fichiers par projet."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

ROLES = ("proprietaire", "editeur", "lecteur")
SESSION_DAYS = 14

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
    pw_hash TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, owner_id INTEGER NOT NULL,
    created REAL NOT NULL, updated REAL NOT NULL, status TEXT NOT NULL DEFAULT 'nouveau');
CREATE TABLE IF NOT EXISTS members (
    project_id INTEGER NOT NULL, user_id INTEGER NOT NULL, role TEXT NOT NULL,
    PRIMARY KEY (project_id, user_id));
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
    created REAL NOT NULL, finished REAL, log TEXT DEFAULT '', error TEXT DEFAULT '', user_id INTEGER);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, user_id INTEGER, ts REAL NOT NULL, text TEXT NOT NULL);
"""


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${dk.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt, dk = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, bytes.fromhex(salt)).split("$")[2], dk)


def _is_empty(db_path: Path) -> bool:
    """Base sans aucun compte (créée vide par erreur)."""
    try:
        con = sqlite3.connect(db_path)
        try:
            return con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        finally:
            con.close()
    except sqlite3.Error:
        return True


class Storage:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "projets").mkdir(exist_ok=True)
        self._lock = threading.Lock()
        db_path = self.root / "baticalc.sqlite"
        old = self.root / "koordinia.sqlite"   # base créée sous l'ancien nom de l'application
        if old.exists() and (not db_path.exists() or _is_empty(db_path)):
            if db_path.exists():
                db_path.unlink()
            old.rename(db_path)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ------------------------------------------------------------------ outils
    def q(self, sql: str, args: tuple = (), one: bool = False):
        with self._lock:
            cur = self.db.execute(sql, args)
            rows = cur.fetchall()
            self.db.commit()
        if one:
            return dict(rows[0]) if rows else None
        return [dict(r) for r in rows]

    def x(self, sql: str, args: tuple = ()) -> int:
        with self._lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur.lastrowid

    def project_dir(self, pid: int) -> Path:
        d = self.root / "projets" / str(int(pid))
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ------------------------------------------------------------------ comptes
    def create_user(self, email: str, name: str, password: str) -> int:
        email = email.strip().lower()
        if self.q("SELECT id FROM users WHERE email=?", (email,), one=True):
            raise ValueError("Un compte existe déjà avec cette adresse.")
        return self.x("INSERT INTO users(email,name,pw_hash,created) VALUES(?,?,?,?)",
                      (email, name.strip(), hash_password(password), time.time()))

    def authenticate(self, email: str, password: str) -> dict | None:
        u = self.q("SELECT * FROM users WHERE email=?", (email.strip().lower(),), one=True)
        if u and check_password(password, u["pw_hash"]):
            return u
        return None

    def new_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        self.x("INSERT INTO sessions(token,user_id,expires) VALUES(?,?,?)",
               (token, user_id, time.time() + SESSION_DAYS * 86400))
        return token

    def session_user(self, token: str | None) -> dict | None:
        if not token:
            return None
        row = self.q("SELECT u.id, u.email, u.name, s.expires FROM sessions s JOIN users u ON u.id=s.user_id "
                     "WHERE s.token=?", (token,), one=True)
        if not row or row["expires"] < time.time():
            return None
        return {"id": row["id"], "email": row["email"], "name": row["name"]}

    def end_session(self, token: str) -> None:
        self.x("DELETE FROM sessions WHERE token=?", (token,))

    # ------------------------------------------------------------------ projets
    def create_project(self, name: str, owner_id: int) -> int:
        now = time.time()
        pid = self.x("INSERT INTO projects(name,owner_id,created,updated) VALUES(?,?,?,?)",
                     (name.strip(), owner_id, now, now))
        self.x("INSERT INTO members(project_id,user_id,role) VALUES(?,?,?)", (pid, owner_id, "proprietaire"))
        self.project_dir(pid)
        return pid

    def projects_for(self, user_id: int) -> list[dict]:
        return self.q("SELECT p.*, m.role, u.name AS owner_name FROM projects p "
                      "JOIN members m ON m.project_id=p.id AND m.user_id=? JOIN users u ON u.id=p.owner_id "
                      "ORDER BY p.updated DESC", (user_id,))

    def project(self, pid: int) -> dict | None:
        return self.q("SELECT * FROM projects WHERE id=?", (pid,), one=True)

    def role(self, pid: int, user_id: int) -> str | None:
        r = self.q("SELECT role FROM members WHERE project_id=? AND user_id=?", (pid, user_id), one=True)
        return r["role"] if r else None

    def touch(self, pid: int, status: str | None = None) -> None:
        if status:
            self.x("UPDATE projects SET updated=?, status=? WHERE id=?", (time.time(), status, pid))
        else:
            self.x("UPDATE projects SET updated=? WHERE id=?", (time.time(), pid))

    def rename_project(self, pid: int, name: str) -> None:
        self.x("UPDATE projects SET name=?, updated=? WHERE id=?", (name.strip(), time.time(), pid))

    def delete_project(self, pid: int) -> None:
        import shutil

        for t in ("members", "jobs", "activity"):
            self.x(f"DELETE FROM {t} WHERE project_id=?", (pid,))
        self.x("DELETE FROM projects WHERE id=?", (pid,))
        shutil.rmtree(self.root / "projets" / str(int(pid)), ignore_errors=True)

    def members(self, pid: int) -> list[dict]:
        return self.q("SELECT u.id, u.email, u.name, m.role FROM members m JOIN users u ON u.id=m.user_id "
                      "WHERE m.project_id=? ORDER BY m.role, u.name", (pid,))

    def set_member(self, pid: int, email: str, role: str) -> dict:
        if role not in ROLES[1:]:
            raise ValueError("Rôle invalide (editeur ou lecteur).")
        u = self.q("SELECT id, email, name FROM users WHERE email=?", (email.strip().lower(),), one=True)
        if not u:
            raise LookupError("Aucun compte avec cette adresse : la personne doit d'abord créer son compte.")
        if self.role(pid, u["id"]) == "proprietaire":
            raise ValueError("Le propriétaire du projet ne peut pas changer de rôle.")
        self.x("INSERT OR REPLACE INTO members(project_id,user_id,role) VALUES(?,?,?)", (pid, u["id"], role))
        return u

    def remove_member(self, pid: int, user_id: int) -> None:
        if self.role(pid, user_id) == "proprietaire":
            raise ValueError("Le propriétaire ne peut pas être retiré.")
        self.x("DELETE FROM members WHERE project_id=? AND user_id=?", (pid, user_id))

    # ------------------------------------------------------------------ journal et tâches
    def log(self, pid: int, user_id: int | None, text: str) -> None:
        self.x("INSERT INTO activity(project_id,user_id,ts,text) VALUES(?,?,?,?)", (pid, user_id, time.time(), text))

    def activity(self, pid: int, limit: int = 50) -> list[dict]:
        return self.q("SELECT a.ts, a.text, u.name FROM activity a LEFT JOIN users u ON u.id=a.user_id "
                      "WHERE a.project_id=? ORDER BY a.id DESC LIMIT ?", (pid, limit))

    def new_job(self, pid: int, kind: str, user_id: int | None) -> int:
        return self.x("INSERT INTO jobs(project_id,kind,status,created,user_id) VALUES(?,?,?,?,?)",
                      (pid, kind, "en_attente", time.time(), user_id))

    def update_job(self, jid: int, status: str, log: str = "", error: str = "") -> None:
        fin = time.time() if status in ("termine", "erreur") else None
        self.x("UPDATE jobs SET status=?, log=?, error=?, finished=? WHERE id=?", (status, log, error, fin, jid))

    def job(self, jid: int) -> dict | None:
        return self.q("SELECT * FROM jobs WHERE id=?", (jid,), one=True)

    def last_job(self, pid: int, kind: str | None = None) -> dict | None:
        if kind:
            return self.q("SELECT * FROM jobs WHERE project_id=? AND kind=? ORDER BY id DESC LIMIT 1", (pid, kind),
                          one=True)
        return self.q("SELECT * FROM jobs WHERE project_id=? ORDER BY id DESC LIMIT 1", (pid,), one=True)
