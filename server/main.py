"""API: multi-team audio labeling platform with SQLite (dev) or Postgres (prod)."""

from __future__ import annotations

import json
import os
import random
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")
FRESH_AUDIO_DIR = os.environ.get("FRESH_AUDIO_DIR", "")
ALGOLIA_APP_ID = os.environ.get("ALGOLIA_APP_ID", "")
ALGOLIA_API_KEY = os.environ.get("ALGOLIA_API_KEY", "")
ALGOLIA_INDEX_NAME = os.environ.get("ALGOLIA_INDEX_NAME", "african_language_podcasts")

REPO_ROOT = Path(__file__).resolve().parent.parent
USE_SQLITE = not DATABASE_URL
DB_PATH = REPO_ROOT / "data" / "audio-label.db"

app = FastAPI(title="audio-label", version="0.5.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


# ── Audio serving ─────────────────────────────────────────────────────────

def _audio_dir() -> Path:
    if FRESH_AUDIO_DIR:
        return Path(FRESH_AUDIO_DIR).resolve()
    return REPO_ROOT / "fresh_audio"

def _validate_audio_path(filename: str) -> Path:
    safe = Path(filename).name
    resolved = (_audio_dir() / safe).resolve()
    if not str(resolved).startswith(str(_audio_dir().resolve())):
        raise HTTPException(status_code=400, detail="Invalid audio path")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found")
    return resolved

@app.get("/audio/{filename:path}")
def serve_audio(filename: str):
    filepath = _validate_audio_path(filename)
    return FileResponse(str(filepath), media_type="audio/wav")


# ── DB abstraction ────────────────────────────────────────────────────────

@contextmanager
def _db():
    if USE_SQLITE:
        (REPO_ROOT / "data").mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    else:
        if not DATABASE_URL:
            raise HTTPException(status_code=503, detail="DATABASE_URL not configured")
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def _real_dict_cursor(conn):
    """Return a cursor that maps column names (RealDictCursor for PG, sqlite3.Row for SQLite)."""
    if USE_SQLITE:
        return conn.cursor()
    import psycopg2.extras
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def _dict_row(row):
    """Convert a DB row to a plain dict."""
    if row is None:
        return None
    return dict(row)


def _dt_now():
    return datetime.now(timezone.utc).isoformat()


# ── Schema ────────────────────────────────────────────────────────────────

def _create_schema() -> None:
    with _db() as conn:
        if USE_SQLITE:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS annotations (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    submitted_at  TEXT NOT NULL DEFAULT (datetime('now')),
                    export_version INTEGER NOT NULL,
                    task_id       TEXT NOT NULL,
                    annotation    TEXT,
                    meta          TEXT NOT NULL DEFAULT '{}',
                    user_id       TEXT,
                    task_uuid     TEXT,
                    project_id    TEXT,
                    time_spent_ms INTEGER
                );
                CREATE TABLE IF NOT EXISTS teams (
                    id          TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    created_by  TEXT NOT NULL,
                    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS team_members (
                    team_id   TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                    user_id   TEXT NOT NULL,
                    role      TEXT NOT NULL DEFAULT 'reviewer',
                    joined_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (team_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS projects (
                    id              TEXT PRIMARY KEY,
                    team_id         TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                    name            TEXT NOT NULL,
                    description     TEXT NOT NULL DEFAULT '',
                    label_config    TEXT NOT NULL DEFAULT '{}',
                    algolia_index   TEXT NOT NULL DEFAULT 'african_language_podcasts',
                    algolia_filters TEXT,
                    iaa_sample_rate REAL NOT NULL DEFAULT 0.1,
                    gold_set_size   INTEGER NOT NULL DEFAULT 0,
                    created_by      TEXT NOT NULL,
                    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id              TEXT PRIMARY KEY,
                    project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    segment_id      TEXT NOT NULL,
                    segment_data    TEXT NOT NULL DEFAULT '{}',
                    task_type       TEXT NOT NULL DEFAULT 'review',
                    gold_annotation TEXT,
                    iaa_parent_id  TEXT REFERENCES tasks(id),
                    assigned_to     TEXT,
                    status          TEXT NOT NULL DEFAULT 'pending',
                    priority        INTEGER NOT NULL DEFAULT 0,
                    locked_at       TEXT,
                    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_unique ON tasks(project_id, segment_id, task_type);
                CREATE TABLE IF NOT EXISTS iaa_scores (
                    id              TEXT PRIMARY KEY,
                    project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    task_original   TEXT NOT NULL REFERENCES tasks(id),
                    task_duplicate  TEXT NOT NULL REFERENCES tasks(id),
                    agreement_score REAL NOT NULL,
                    metric          TEXT NOT NULL DEFAULT 'wer',
                    computed_at     TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS exports (
                    id            TEXT PRIMARY KEY,
                    project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    arweave_tx_id TEXT,
                    batch_size    INTEGER NOT NULL DEFAULT 0,
                    filters       TEXT NOT NULL DEFAULT '{}',
                    status        TEXT NOT NULL DEFAULT 'pending',
                    created_by    TEXT NOT NULL,
                    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
                );
            """)
        else:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS annotations (
                    id            SERIAL PRIMARY KEY,
                    submitted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    export_version INTEGER NOT NULL,
                    task_id       TEXT NOT NULL,
                    annotation    JSONB,
                    meta          JSONB NOT NULL DEFAULT '{}',
                    user_id       TEXT
                );
            """)
            cur.execute("ALTER TABLE annotations ADD COLUMN IF NOT EXISTS task_uuid UUID REFERENCES tasks(id);")
            cur.execute("ALTER TABLE annotations ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id);")
            cur.execute("ALTER TABLE annotations ADD COLUMN IF NOT EXISTS time_spent_ms INT;")
            cur.execute("""
                CREATE EXTENSION IF NOT EXISTS "pgcrypto";
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS teams (
                    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    name        TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    created_by  TEXT NOT NULL,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS team_members (
                    team_id   UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                    user_id   TEXT NOT NULL,
                    role      TEXT NOT NULL DEFAULT 'reviewer',
                    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (team_id, user_id)
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    team_id         UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                    name            TEXT NOT NULL,
                    description     TEXT NOT NULL DEFAULT '',
                    label_config    JSONB NOT NULL DEFAULT '{}',
                    algolia_index   TEXT NOT NULL DEFAULT 'african_language_podcasts',
                    algolia_filters TEXT,
                    iaa_sample_rate REAL NOT NULL DEFAULT 0.1,
                    gold_set_size   INT NOT NULL DEFAULT 0,
                    created_by      TEXT NOT NULL,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    segment_id      TEXT NOT NULL,
                    segment_data    JSONB NOT NULL DEFAULT '{}',
                    task_type       TEXT NOT NULL DEFAULT 'review',
                    gold_annotation JSONB,
                    iaa_parent_id  UUID REFERENCES tasks(id),
                    assigned_to     TEXT,
                    status          TEXT NOT NULL DEFAULT 'pending',
                    priority        INT NOT NULL DEFAULT 0,
                    locked_at       TIMESTAMPTZ,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(project_id, segment_id, task_type)
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS iaa_scores (
                    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    task_original   UUID NOT NULL REFERENCES tasks(id),
                    task_duplicate  UUID NOT NULL REFERENCES tasks(id),
                    agreement_score REAL NOT NULL,
                    metric          TEXT NOT NULL DEFAULT 'wer',
                    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS exports (
                    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    project_id    UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    arweave_tx_id TEXT,
                    batch_size    INT NOT NULL DEFAULT 0,
                    filters       JSONB NOT NULL DEFAULT '{}',
                    status        TEXT NOT NULL DEFAULT 'pending',
                    created_by    TEXT NOT NULL,
                    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            conn.commit()


@app.on_event("startup")
def startup() -> None:
    _create_schema()


# ── Auth ───────────────────────────────────────────────────────────────────

def _require_user(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = auth[len("Bearer "):]
    if not SUPABASE_JWT_SECRET:
        if token == "dev-token":
            return "dev-user"
        raise HTTPException(status_code=500, detail="SUPABASE_JWT_SECRET not configured and invalid dev token")
    import jwt
    try:
        payload = jwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"], options={"verify_aud": False})
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
    user_id: Optional[str] = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing sub claim")
    return user_id


def _require_team_member(conn, user_id: str, team_id: str, roles: list[str] | None = None) -> dict:
    cur = _real_dict_cursor(conn)
    cur.execute("SELECT * FROM team_members WHERE team_id = ?" if USE_SQLITE else "SELECT * FROM team_members WHERE team_id = %s", (team_id,))
    rows = cur.fetchall()
    # Filter by user_id in application code (handles both DBs the same way)
    row = None
    for r in rows:
        if dict(r)["user_id"] == user_id:
            row = dict(r)
            break
    if not row:
        raise HTTPException(status_code=403, detail="Not a member of this team")
    if roles and row["role"] not in roles:
        raise HTTPException(status_code=403, detail=f"Requires role in {roles}")
    return row


def _require_project_access(conn, user_id: str, project_id: str) -> dict:
    cur = _real_dict_cursor(conn)
    cur.execute(
        "SELECT p.* FROM projects p JOIN team_members tm ON tm.team_id = p.team_id WHERE p.id = ? AND tm.user_id = ?" if USE_SQLITE
        else "SELECT p.* FROM projects p JOIN team_members tm ON tm.team_id = p.team_id WHERE p.id = %s AND tm.user_id = %s",
        (project_id, user_id),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=403, detail="Project not found or no access")
    return dict(row)


def _new_id():
    return str(uuid.uuid4())


def _wer(reference: str, hypothesis: str) -> float:
    ref_words = reference.strip().split()
    hyp_words = hypothesis.strip().split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    n = len(ref_words)
    m = len(hyp_words)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if ref_words[i - 1] == hyp_words[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
    return d[n][m] / n


# ── Pydantic models ──────────────────────────────────────────────────────

class TeamCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""

class TeamUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

class MemberInvite(BaseModel):
    user_id: str
    role: str = "reviewer"

class ProjectCreate(BaseModel):
    team_id: str
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    label_config: dict = {}
    algolia_index: str = "african_language_podcasts"
    algolia_filters: Optional[str] = None
    iaa_sample_rate: float = 0.1
    gold_set_size: int = 0

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    label_config: Optional[dict] = None
    algolia_filters: Optional[str] = None
    iaa_sample_rate: Optional[float] = None
    gold_set_size: Optional[int] = None

class ImportRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=10000)
    filters: Optional[str] = None

class AnnotationSubmit(BaseModel):
    transcript_corrected: str
    labels: list[str] = []
    preferred_model: Optional[str] = None
    notes: str = ""
    time_spent_ms: int = 0
    accepted_by_reviewer: Optional[bool] = None

class ExportCreate(BaseModel):
    filters: dict = {}


# ── Teams ─────────────────────────────────────────────────────────────────

@app.post("/api/teams")
def create_team(body: TeamCreate, request: Request):
    user_id = _require_user(request)
    tid = _new_id()
    now = _dt_now()
    with _db() as conn:
        cur = conn.cursor()
        if USE_SQLITE:
            cur.execute("INSERT INTO teams (id, name, description, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
                        (tid, body.name, body.description, user_id, now))
            cur.execute("INSERT INTO team_members (team_id, user_id, role, joined_at) VALUES (?, ?, 'owner', ?)",
                        (tid, user_id, now))
        else:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                "INSERT INTO teams (name, description, created_by) VALUES (%s, %s, %s) RETURNING id, name, description, created_by, created_at",
                (body.name, body.description, user_id),
            )
            tid = dict(cur.fetchone())["id"]
            cur.execute("INSERT INTO team_members (team_id, user_id, role) VALUES (%s, %s, 'owner')", (tid, user_id))
    return {"id": tid, "name": body.name, "description": body.description, "created_by": user_id, "role": "owner"}


@app.get("/api/teams")
def list_teams(request: Request):
    user_id = _require_user(request)
    with _db() as conn:
        cur = _real_dict_cursor(conn)
        if USE_SQLITE:
            cur.execute("SELECT t.*, tm.role FROM teams t JOIN team_members tm ON tm.team_id = t.id WHERE tm.user_id = ? ORDER BY t.created_at DESC", (user_id,))
        else:
            cur.execute("SELECT t.*, tm.role FROM teams t JOIN team_members tm ON tm.team_id = t.id WHERE tm.user_id = %s ORDER BY t.created_at DESC", (user_id,))
        rows = [dict(r) for r in cur.fetchall()]
    return {"teams": rows}


@app.get("/api/teams/{team_id}")
def get_team(team_id: str, request: Request):
    user_id = _require_user(request)
    with _db() as conn:
        _require_team_member(conn, user_id, team_id)
        cur = _real_dict_cursor(conn)
        if USE_SQLITE:
            cur.execute("SELECT * FROM teams WHERE id = ?", (team_id,))
        else:
            cur.execute("SELECT * FROM teams WHERE id = %s", (team_id,))
        team = cur.fetchone()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        cur.execute("SELECT * FROM team_members WHERE team_id = ? ORDER BY joined_at" if USE_SQLITE else "SELECT * FROM team_members WHERE team_id = %s ORDER BY joined_at", (team_id,))
        members = [dict(r) for r in cur.fetchall()]
    return {"team": dict(team), "members": members}


@app.put("/api/teams/{team_id}")
def update_team(team_id: str, body: TeamUpdate, request: Request):
    user_id = _require_user(request)
    with _db() as conn:
        _require_team_member(conn, user_id, team_id, roles=["owner", "admin"])
        updates = {}
        if body.name is not None:
            updates["name"] = body.name
        if body.description is not None:
            updates["description"] = body.description
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")
        set_clause = ", ".join(f"{k} = ?" if USE_SQLITE else f"{k} = %s" for k in updates)
        vals = list(updates.values()) + [team_id]
        cur = _real_dict_cursor(conn)
        cur.execute(f"UPDATE teams SET {set_clause} WHERE id = ?" if USE_SQLITE else f"UPDATE teams SET {set_clause} WHERE id = %s", vals)
        cur.execute("SELECT * FROM teams WHERE id = ?" if USE_SQLITE else "SELECT * FROM teams WHERE id = %s", (team_id,))
        team = cur.fetchone()
    return {"team": dict(team)}


@app.delete("/api/teams/{team_id}")
def delete_team(team_id: str, request: Request):
    user_id = _require_user(request)
    with _db() as conn:
        _require_team_member(conn, user_id, team_id, roles=["owner"])
        cur = conn.cursor()
        cur.execute("DELETE FROM teams WHERE id = ?" if USE_SQLITE else "DELETE FROM teams WHERE id = %s", (team_id,))
    return {"ok": True}


# ── Team Members ──────────────────────────────────────────────────────────

@app.post("/api/teams/{team_id}/members")
def invite_member(team_id: str, body: MemberInvite, request: Request):
    user_id = _require_user(request)
    now = _dt_now()
    with _db() as conn:
        _require_team_member(conn, user_id, team_id, roles=["owner", "admin"])
        cur = conn.cursor()
        try:
            if USE_SQLITE:
                cur.execute("INSERT INTO team_members (team_id, user_id, role, joined_at) VALUES (?, ?, ?, ?)",
                            (team_id, body.user_id, body.role, now))
            else:
                cur.execute("INSERT INTO team_members (team_id, user_id, role) VALUES (%s, %s, %s)",
                            (team_id, body.user_id, body.role))
        except Exception:
            raise HTTPException(status_code=409, detail="User is already a member")
    return {"ok": True}


@app.delete("/api/teams/{team_id}/members/{member_id}")
def remove_member(team_id: str, member_id: str, request: Request):
    user_id = _require_user(request)
    with _db() as conn:
        _require_team_member(conn, user_id, team_id, roles=["owner", "admin"])
        cur = conn.cursor()
        cur.execute("DELETE FROM team_members WHERE team_id = ? AND user_id = ?" if USE_SQLITE else "DELETE FROM team_members WHERE team_id = %s AND user_id = %s",
                    (team_id, member_id))
    return {"ok": True}


# ── Projects ──────────────────────────────────────────────────────────────

@app.post("/api/projects")
def create_project(body: ProjectCreate, request: Request):
    user_id = _require_user(request)
    pid = _new_id()
    now = _dt_now()
    with _db() as conn:
        _require_team_member(conn, user_id, body.team_id, roles=["owner", "admin"])
        label_json = json.dumps(body.label_config)
        cur = conn.cursor()
        if USE_SQLITE:
            cur.execute(
                "INSERT INTO projects (id, team_id, name, description, label_config, algolia_index, algolia_filters, iaa_sample_rate, gold_set_size, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (pid, body.team_id, body.name, body.description, label_json, body.algolia_index, body.algolia_filters, body.iaa_sample_rate, body.gold_set_size, user_id, now),
            )
        else:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """INSERT INTO projects (team_id, name, description, label_config, algolia_index, algolia_filters, iaa_sample_rate, gold_set_size, created_by)
                   VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s) RETURNING *""",
                (body.team_id, body.name, body.description, label_json, body.algolia_index, body.algolia_filters, body.iaa_sample_rate, body.gold_set_size, user_id),
            )
            pid = dict(cur.fetchone())["id"]
    return {"project": {"id": pid, "name": body.name, "description": body.description, "team_id": body.team_id}}


@app.get("/api/teams/{team_id}/projects")
def list_projects(team_id: str, request: Request):
    user_id = _require_user(request)
    with _db() as conn:
        _require_team_member(conn, user_id, team_id)
        cur = _real_dict_cursor(conn)
        if USE_SQLITE:
            cur.execute("""
                SELECT p.*,
                    (SELECT COUNT(*) FROM tasks t WHERE t.project_id = p.id) as total_tasks,
                    (SELECT COUNT(*) FROM tasks t WHERE t.project_id = p.id AND t.status = 'approved') as approved_tasks,
                    (SELECT COUNT(*) FROM tasks t WHERE t.project_id = p.id AND t.status = 'submitted') as submitted_tasks
                FROM projects p WHERE p.team_id = ? ORDER BY p.created_at DESC
            """, (team_id,))
        else:
            cur.execute("""
                SELECT p.*,
                    (SELECT COUNT(*) FROM tasks t WHERE t.project_id = p.id) as total_tasks,
                    (SELECT COUNT(*) FROM tasks t WHERE t.project_id = p.id AND t.status = 'approved') as approved_tasks,
                    (SELECT COUNT(*) FROM tasks t WHERE t.project_id = p.id AND t.status = 'submitted') as submitted_tasks
                FROM projects p WHERE p.team_id = %s ORDER BY p.created_at DESC
            """, (team_id,))
        rows = [dict(r) for r in cur.fetchall()]
    return {"projects": rows}


@app.get("/api/projects/{project_id}")
def get_project(project_id: str, request: Request):
    user_id = _require_user(request)
    with _db() as conn:
        project = _require_project_access(conn, user_id, project_id)
        role = None
        cur = _real_dict_cursor(conn)
        cur.execute("SELECT tm.role FROM team_members tm WHERE tm.team_id = ? AND tm.user_id = ?" if USE_SQLITE else "SELECT tm.role FROM team_members tm WHERE tm.team_id = %s AND tm.user_id = %s",
                    (project["team_id"], user_id))
        row = cur.fetchone()
        if row:
            role = dict(row)["role"]
        if USE_SQLITE:
            cur.execute("""
                SELECT
                    COUNT(*) AS total_tasks,
                    COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                    COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress,
                    COUNT(*) FILTER (WHERE status = 'submitted') AS submitted,
                    COUNT(*) FILTER (WHERE status = 'approved') AS approved,
                    COUNT(*) FILTER (WHERE status = 'rejected') AS rejected
                FROM tasks WHERE project_id = ?
            """, (project_id,))
        else:
            cur.execute("""
                SELECT
                    COUNT(*) AS total_tasks,
                    COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                    COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress,
                    COUNT(*) FILTER (WHERE status = 'submitted') AS submitted,
                    COUNT(*) FILTER (WHERE status = 'approved') AS approved,
                    COUNT(*) FILTER (WHERE status = 'rejected') AS rejected
                FROM tasks WHERE project_id = %s
            """, (project_id,))
        stats = dict(cur.fetchone())
    return {"project": project, "role": role, "stats": stats}


@app.put("/api/projects/{project_id}")
def update_project(project_id: str, body: ProjectUpdate, request: Request):
    user_id = _require_user(request)
    with _db() as conn:
        project = _require_project_access(conn, user_id, project_id)
        _require_team_member(conn, user_id, str(project["team_id"]), roles=["owner", "admin"])
        updates = {}
        if body.name is not None:
            updates["name"] = body.name
        if body.description is not None:
            updates["description"] = body.description
        if body.label_config is not None:
            updates["label_config"] = json.dumps(body.label_config)
        if body.algolia_filters is not None:
            updates["algolia_filters"] = body.algolia_filters
        if body.iaa_sample_rate is not None:
            updates["iaa_sample_rate"] = body.iaa_sample_rate
        if body.gold_set_size is not None:
            updates["gold_set_size"] = body.gold_set_size
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")
        set_clause = ", ".join(f"{k} = ?" if USE_SQLITE else f"{k} = %s" for k in updates)
        vals = list(updates.values()) + [project_id]
        cur = _real_dict_cursor(conn)
        cur.execute(f"UPDATE projects SET {set_clause} WHERE id = ?" if USE_SQLITE else f"UPDATE projects SET {set_clause} WHERE id = %s", vals)
        cur.execute("SELECT * FROM projects WHERE id = ?" if USE_SQLITE else "SELECT * FROM projects WHERE id = %s", (project_id,))
        updated = cur.fetchone()
    return {"project": dict(updated) if updated else {}}


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str, request: Request):
    user_id = _require_user(request)
    with _db() as conn:
        project = _require_project_access(conn, user_id, project_id)
        _require_team_member(conn, user_id, str(project["team_id"]), roles=["owner"])
        cur = conn.cursor()
        cur.execute("DELETE FROM projects WHERE id = ?" if USE_SQLITE else "DELETE FROM projects WHERE id = %s", (project_id,))
    return {"ok": True}


# ── Task Import from Algolia ──────────────────────────────────────────────

@app.post("/api/projects/{project_id}/import")
async def import_segments(project_id: str, body: ImportRequest, request: Request):
    user_id = _require_user(request)
    with _db() as conn:
        project = _require_project_access(conn, user_id, project_id)
        _require_team_member(conn, user_id, str(project["team_id"]), roles=["owner", "admin"])

    if not ALGOLIA_APP_ID or not ALGOLIA_API_KEY:
        raise HTTPException(status_code=503, detail="Algolia not configured")

    filters = body.filters or project.get("algolia_filters") or ""
    index_name = project.get("algolia_index") or "african_language_podcasts"

    try:
        url = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/{index_name}/query"
        payload = {
            "params": f"hitsPerPage={body.limit}{'&filters=' + filters if filters else ''}&attributesToRetrieve=objectID,transcript,title,audio_path,metadata,categories,_tags"
        }
        headers = {
            "X-Algolia-Application-Id": ALGOLIA_APP_ID,
            "X-Algolia-API-Key": ALGOLIA_API_KEY,
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=payload, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            hits = data.get("hits", [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Algolia search failed: {e}")

    if not hits:
        return {"imported": 0, "total": 0, "message": "No segments match the given filters"}

    iaa_rate = project["iaa_sample_rate"]
    gold_size = project["gold_set_size"]
    imported = 0

    with _db() as conn:
        for hit in hits:
            segment_id = hit.get("objectID")
            if not segment_id:
                continue
            segment_data = {
                "objectID": segment_id,
                "transcript": hit.get("transcript", ""),
                "title": hit.get("title", ""),
                "audio_url": f"/audio/{Path(hit.get('metadata', {}).get('audio_path', segment_id)).name}",
                "metadata": hit.get("metadata", {}),
                "categories": hit.get("categories", {}),
                "_tags": hit.get("_tags", []),
            }
            tid = _new_id()
            now = _dt_now()
            cur = conn.cursor()
            try:
                if USE_SQLITE:
                    cur.execute(
                        "INSERT OR IGNORE INTO tasks (id, project_id, segment_id, segment_data, task_type, status, created_at) VALUES (?, ?, ?, ?, 'review', 'pending', ?)",
                        (tid, project_id, segment_id, json.dumps(segment_data), now),
                    )
                else:
                    cur.execute(
                        """INSERT INTO tasks (project_id, segment_id, segment_data, task_type, status)
                           VALUES (%s, %s, %s::jsonb, 'review', 'pending')
                           ON CONFLICT (project_id, segment_id, task_type) DO NOTHING""",
                        (project_id, segment_id, json.dumps(segment_data)),
                    )
                # Check rowcount for SQLite — rowcount is 0 for INSERT OR IGNORE conflict
                if USE_SQLITE:
                    imported += 1
                elif cur.rowcount > 0:
                    imported += 1
            except Exception:
                conn.rollback()
                raise

        if USE_SQLITE and imported > 0:
            imported = list(hits)  # Recompute below
            # Simple: count how many review tasks now exist
            cur = _real_dict_cursor(conn)
            cur.execute("SELECT COUNT(*) as cnt FROM tasks WHERE project_id = ? AND task_type = 'review'", (project_id,))
            imported = dict(cur.fetchone())["cnt"]

        # Seed gold set tasks
        if gold_size > 0:
            cur = _real_dict_cursor(conn)
            cur.execute(
                "SELECT id FROM tasks WHERE project_id = ? AND task_type = 'review' AND status = 'pending' LIMIT ?" if USE_SQLITE
                else "SELECT id FROM tasks WHERE project_id = %s AND task_type = 'review' AND status = 'pending' LIMIT %s",
                (project_id, gold_size),
            )
            gold_candidates = cur.fetchall()
            for gc in gold_candidates:
                gc = dict(gc)
                cur = conn.cursor()
                cur.execute("UPDATE tasks SET task_type = 'gold' WHERE id = ?" if USE_SQLITE else "UPDATE tasks SET task_type = 'gold' WHERE id = %s", (gc["id"],))

        # Create IAA duplicates
        if iaa_rate > 0:
            cur = _real_dict_cursor(conn)
            cur.execute(
                "SELECT id, segment_data FROM tasks WHERE project_id = ? AND task_type = 'review' AND status = 'pending'" if USE_SQLITE
                else "SELECT id, segment_data FROM tasks WHERE project_id = %s AND task_type = 'review' AND status = 'pending'",
                (project_id,),
            )
            review_tasks = [dict(r) for r in cur.fetchall()]
            sample_count = max(1, min(int(len(review_tasks) * iaa_rate), len(review_tasks)))
            sampled = random.sample(review_tasks, sample_count) if sample_count <= len(review_tasks) else review_tasks
            for original in sampled:
                dup_id = _new_id()
                now = _dt_now()
                seg_data = original.get("segment_data", {})
                if isinstance(seg_data, str):
                    seg_data = json.loads(seg_data)
                cur = conn.cursor()
                try:
                    if USE_SQLITE:
                        cur.execute(
                            "INSERT OR IGNORE INTO tasks (id, project_id, segment_id, segment_data, task_type, iaa_parent_id, status, created_at) VALUES (?, ?, ?, ?, 'iaa_duplicate', ?, 'pending', ?)",
                            (dup_id, project_id, seg_data.get("objectID", ""), json.dumps(seg_data), original["id"], now),
                        )
                    else:
                        cur.execute(
                            """INSERT INTO tasks (project_id, segment_id, segment_data, task_type, iaa_parent_id, status)
                               VALUES (%s, %s, %s::jsonb, 'iaa_duplicate', %s, 'pending')
                               ON CONFLICT (project_id, segment_id, task_type) DO NOTHING""",
                            (project_id, seg_data.get("objectID", ""), json.dumps(seg_data), original["id"]),
                        )
                except Exception:
                    conn.rollback()

    return {"imported": imported, "total": len(hits)}


# ── Tasks ─────────────────────────────────────────────────────────────────

@app.get("/api/projects/{project_id}/tasks")
def list_tasks(project_id: str, request: Request,
               status: Optional[str] = Query(None),
               task_type: Optional[str] = Query(None),
               assigned_to: Optional[str] = Query(None),
               limit: int = Query(100, ge=1, le=1000),
               offset_val: int = Query(0, ge=0, alias="offset")):
    user_id = _require_user(request)
    with _db() as conn:
        _require_project_access(conn, user_id, project_id)
        clauses = ["t.project_id = ?" if USE_SQLITE else "t.project_id = %s"]
        params: list[Any] = [project_id]
        if status:
            clauses.append("t.status = ?" if USE_SQLITE else "t.status = %s")
            params.append(status)
        if task_type:
            clauses.append("t.task_type = ?" if USE_SQLITE else "t.task_type = %s")
            params.append(task_type)
        if assigned_to:
            clauses.append("t.assigned_to = ?" if USE_SQLITE else "t.assigned_to = %s")
            params.append(assigned_to)
        where = " AND ".join(clauses)
        cur = _real_dict_cursor(conn)
        if USE_SQLITE:
            cur.execute(f"SELECT t.* FROM tasks t WHERE {where} ORDER BY t.priority DESC, t.created_at ASC LIMIT ? OFFSET ?",
                        params + [limit, offset_val])
            rows = cur.fetchall()
            cur.execute(f"SELECT COUNT(*) as cnt FROM tasks t WHERE {where}", params)
            total = dict(cur.fetchone())["cnt"]
        else:
            cur.execute(f"SELECT t.* FROM tasks t WHERE {where} ORDER BY t.priority DESC, t.created_at ASC LIMIT %s OFFSET %s",
                        params + [limit, offset_val])
            rows = cur.fetchall()
            cur.execute(f"SELECT COUNT(*) as cnt FROM tasks t WHERE {where}", params)
            total = dict(cur.fetchone())["cnt"]
        tasks_out = []
        for r in rows:
            d = dict(r)
            if "segment_data" in d and isinstance(d["segment_data"], str):
                try:
                    d["segment_data"] = json.loads(d["segment_data"])
                except Exception:
                    pass
            tasks_out.append(d)
    return {"tasks": tasks_out, "total": total}


@app.get("/api/projects/{project_id}/tasks/next")
def next_task(project_id: str, request: Request):
    user_id = _require_user(request)
    with _db() as conn:
        _require_project_access(conn, user_id, project_id)
        cur = _real_dict_cursor(conn)
        if USE_SQLITE:
            cur.execute(
                "SELECT t.* FROM tasks t WHERE t.project_id = ? AND t.status = 'pending' ORDER BY t.priority DESC, t.created_at ASC LIMIT 1",
                (project_id,),
            )
        else:
            cur.execute(
                "SELECT t.* FROM tasks t WHERE t.project_id = %s AND t.status = 'pending' ORDER BY t.priority DESC, t.created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED",
                (project_id,),
            )
        task = cur.fetchone()
        if not task:
            return {"task": None, "message": "No pending tasks"}
        now = _dt_now()
        cur.execute(
            "UPDATE tasks SET status = 'in_progress', assigned_to = ?, locked_at = ? WHERE id = ?" if USE_SQLITE
            else "UPDATE tasks SET status = 'in_progress', assigned_to = %s, locked_at = NOW() WHERE id = %s",
            (user_id, now, task["id"]) if USE_SQLITE else (user_id, task["id"]),
        )
        d = dict(task)
        if "segment_data" in d and isinstance(d["segment_data"], str):
            try:
                d["segment_data"] = json.loads(d["segment_data"])
            except Exception:
                pass
    return {"task": d}


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str, request: Request):
    user_id = _require_user(request)
    with _db() as conn:
        cur = _real_dict_cursor(conn)
        cur.execute("SELECT t.* FROM tasks t WHERE t.id = ?" if USE_SQLITE else "SELECT t.* FROM tasks t WHERE t.id = %s", (task_id,))
        task = cur.fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_project_access(conn, user_id, str(task["project_id"]))
        d = dict(task)
        if "segment_data" in d and isinstance(d["segment_data"], str):
            try:
                d["segment_data"] = json.loads(d["segment_data"])
            except Exception:
                pass
    return {"task": d}


@app.post("/api/tasks/{task_id}/claim")
def claim_task(task_id: str, request: Request):
    user_id = _require_user(request)
    now = _dt_now()
    with _db() as conn:
        cur = _real_dict_cursor(conn)
        cur.execute("SELECT * FROM tasks WHERE id = ?" if USE_SQLITE else "SELECT * FROM tasks WHERE id = %s FOR UPDATE", (task_id,))
        task = cur.fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_project_access(conn, user_id, str(task["project_id"]))
        if task["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"Task already {task['status']}")
        cur.execute(
            "UPDATE tasks SET status = 'in_progress', assigned_to = ?, locked_at = ? WHERE id = ?" if USE_SQLITE
            else "UPDATE tasks SET status = 'in_progress', assigned_to = %s, locked_at = NOW() WHERE id = %s",
            (user_id, now, task_id) if USE_SQLITE else (user_id, task_id),
        )
    return {"ok": True}


@app.post("/api/tasks/{task_id}/skip")
def skip_task(task_id: str, request: Request):
    user_id = _require_user(request)
    with _db() as conn:
        cur = _real_dict_cursor(conn)
        cur.execute("SELECT * FROM tasks WHERE id = ?" if USE_SQLITE else "SELECT * FROM tasks WHERE id = %s", (task_id,))
        task = cur.fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_project_access(conn, user_id, str(task["project_id"]))
        cur.execute(
            "UPDATE tasks SET status = 'pending', assigned_to = NULL, locked_at = NULL WHERE id = ?" if USE_SQLITE
            else "UPDATE tasks SET status = 'pending', assigned_to = NULL, locked_at = NULL WHERE id = %s",
            (task_id,),
        )
    return {"ok": True}


@app.post("/api/tasks/{task_id}/submit")
def submit_annotation(task_id: str, body: AnnotationSubmit, request: Request):
    user_id = _require_user(request)
    now = _dt_now()
    with _db() as conn:
        cur = _real_dict_cursor(conn)
        cur.execute("SELECT * FROM tasks WHERE id = ?" if USE_SQLITE else "SELECT * FROM tasks WHERE id = %s", (task_id,))
        task = cur.fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_project_access(conn, user_id, str(task["project_id"]))
        if task["status"] not in ("in_progress", "pending"):
            raise HTTPException(status_code=409, detail=f"Task already {task['status']}")

        annotation = {
            "transcript_corrected": body.transcript_corrected,
            "labels": body.labels,
            "preferred_model": body.preferred_model,
            "notes": body.notes,
            "accepted_by_reviewer": body.accepted_by_reviewer,
        }
        annotation_json = json.dumps(annotation)
        meta_json = json.dumps({"task_type": task["task_type"], "segment_id": task["segment_id"]})

        if USE_SQLITE:
            cur.execute(
                "INSERT INTO annotations (submitted_at, export_version, task_id, annotation, meta, user_id, task_uuid, project_id, time_spent_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (now, 2, str(task["id"]), annotation_json, meta_json, user_id, task["id"], task["project_id"], body.time_spent_ms),
            )
            ann_id = cur.lastrowid
        else:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                "INSERT INTO annotations (submitted_at, export_version, task_id, annotation, meta, user_id, task_uuid, project_id, time_spent_ms) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s) RETURNING id",
                (now, 2, str(task["id"]), annotation_json, meta_json, user_id, task["id"], task["project_id"], body.time_spent_ms),
            )
            ann_id = dict(cur.fetchone())["id"]

        new_status = "submitted"
        cur.execute("UPDATE tasks SET status = ? WHERE id = ?" if USE_SQLITE else "UPDATE tasks SET status = %s WHERE id = %s", (new_status, task_id))

        # Compute IAA if this is a duplicate
        if task["task_type"] == "iaa_duplicate" and task["iaa_parent_id"]:
            parent_id = task["iaa_parent_id"]
            cur = _real_dict_cursor(conn)
            cur.execute(
                "SELECT annotation FROM annotations WHERE task_uuid = ? ORDER BY submitted_at DESC LIMIT 1" if USE_SQLITE
                else "SELECT annotation FROM annotations WHERE task_uuid = %s ORDER BY submitted_at DESC LIMIT 1",
                (parent_id,),
            )
            parent_ann = cur.fetchone()
            if parent_ann:
                parent_data = parent_ann["annotation"]
                if isinstance(parent_data, str):
                    parent_data = json.loads(parent_data)
                parent_text = parent_data.get("transcript_corrected", "")
                child_text = body.transcript_corrected
                wer_score = _wer(parent_text, child_text)
                iaa_id = _new_id()
                cur = conn.cursor()
                if USE_SQLITE:
                    cur.execute(
                        "INSERT INTO iaa_scores (id, project_id, task_original, task_duplicate, agreement_score, metric, computed_at) VALUES (?, ?, ?, ?, ?, 'wer', ?)",
                        (iaa_id, task["project_id"], parent_id, task["id"], 1.0 - wer_score, now),
                    )
                else:
                    cur.execute(
                        "INSERT INTO iaa_scores (project_id, task_original, task_duplicate, agreement_score, metric) VALUES (%s, %s, %s, %s, 'wer')",
                        (task["project_id"], parent_id, task["id"], 1.0 - wer_score),
                    )
    return {"ok": True, "annotation_id": ann_id}


# ── Progress ──────────────────────────────────────────────────────────────

@app.get("/api/projects/{project_id}/progress")
def get_progress(project_id: str, request: Request):
    user_id = _require_user(request)
    with _db() as conn:
        _require_project_access(conn, user_id, project_id)
        cur = _real_dict_cursor(conn)
        cur.execute(
            "SELECT task_id FROM annotations WHERE project_id = ? AND user_id = ?" if USE_SQLITE
            else "SELECT task_id FROM annotations WHERE project_id = %s AND user_id = %s",
            (project_id, user_id),
        )
        completed = [dict(r)["task_id"] for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) as total FROM tasks WHERE project_id = ?" if USE_SQLITE else "SELECT COUNT(*) as total FROM tasks WHERE project_id = %s", (project_id,))
        total = dict(cur.fetchone())["total"]
    return {"completed_task_ids": completed, "total": total}


# ── QA / IAA ──────────────────────────────────────────────────────────────

@app.get("/api/projects/{project_id}/qa/stats")
def qa_stats(project_id: str, request: Request):
    user_id = _require_user(request)
    with _db() as conn:
        _require_project_access(conn, user_id, project_id)
        cur = _real_dict_cursor(conn)
        if USE_SQLITE:
            cur.execute("""
                SELECT
                    COUNT(*) AS total_iaa,
                    AVG(agreement_score) AS avg_agreement,
                    COUNT(*) AS high_agreement
                FROM iaa_scores WHERE project_id = ?
            """, (project_id,))
        else:
            cur.execute("""
                SELECT
                    COUNT(*) AS total_iaa,
                    AVG(agreement_score) AS avg_agreement,
                    COUNT(*) FILTER (WHERE agreement_score >= 0.8) AS high_agreement
                FROM iaa_scores WHERE project_id = %s
            """, (project_id,))
        iaa_stats = dict(cur.fetchone())

        cur.execute(
            "SELECT a.user_id, COUNT(*) as tasks_done, AVG(a.time_spent_ms) as avg_time_ms FROM annotations a JOIN tasks t ON t.id = a.task_uuid WHERE t.project_id = ? AND a.user_id IS NOT NULL GROUP BY a.user_id ORDER BY tasks_done DESC" if USE_SQLITE
            else "SELECT a.user_id, COUNT(*) as tasks_done, AVG(a.time_spent_ms)::INT as avg_time_ms FROM annotations a JOIN tasks t ON t.id = a.task_uuid WHERE t.project_id = %s AND a.user_id IS NOT NULL GROUP BY a.user_id ORDER BY tasks_done DESC",
            (project_id,),
        )
        reviewer_stats = [dict(r) for r in cur.fetchall()]

        cur.execute(
            "SELECT a.user_id, COUNT(*) as gold_tasks FROM annotations a JOIN tasks t ON t.id = a.task_uuid WHERE t.project_id = ? AND t.task_type = 'gold' AND a.user_id IS NOT NULL GROUP BY a.user_id" if USE_SQLITE
            else "SELECT a.user_id, COUNT(*) as gold_tasks FROM annotations a JOIN tasks t ON t.id = a.task_uuid WHERE t.project_id = %s AND t.task_type = 'gold' AND a.user_id IS NOT NULL GROUP BY a.user_id",
            (project_id,),
        )
        gold_stats = [dict(r) for r in cur.fetchall()]

    return {"iaa": iaa_stats, "reviewers": reviewer_stats, "gold": gold_stats}


# ── Exports ───────────────────────────────────────────────────────────────

@app.post("/api/projects/{project_id}/exports")
def create_export(project_id: str, body: ExportCreate, request: Request):
    user_id = _require_user(request)
    eid = _new_id()
    now = _dt_now()
    with _db() as conn:
        project = _require_project_access(conn, user_id, project_id)
        _require_team_member(conn, user_id, str(project["team_id"]), roles=["owner", "admin"])
        cur = conn.cursor()
        if USE_SQLITE:
            cur.execute(
                "INSERT INTO exports (id, project_id, batch_size, filters, status, created_by, created_at) VALUES (?, ?, 0, ?, 'pending', ?, ?)",
                (eid, project_id, json.dumps(body.filters), user_id, now),
            )
        else:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                "INSERT INTO exports (project_id, batch_size, filters, status, created_by) VALUES (%s, %s, %s::jsonb, 'pending', %s) RETURNING *",
                (project_id, 0, json.dumps(body.filters), user_id),
            )
            eid = dict(cur.fetchone())["id"]
    return {"export": {"id": eid, "project_id": project_id, "status": "pending"}}


@app.get("/api/projects/{project_id}/exports")
def list_exports(project_id: str, request: Request):
    user_id = _require_user(request)
    with _db() as conn:
        _require_project_access(conn, user_id, project_id)
        cur = _real_dict_cursor(conn)
        cur.execute("SELECT * FROM exports WHERE project_id = ? ORDER BY created_at DESC" if USE_SQLITE else "SELECT * FROM exports WHERE project_id = %s ORDER BY created_at DESC", (project_id,))
        rows = [dict(r) for r in cur.fetchall()]
    return {"exports": rows}


# ── Health ────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"ok": True, "version": "0.5.0", "db": "sqlite" if USE_SQLITE else "postgres"}