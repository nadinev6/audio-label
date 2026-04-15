"""API: serves tasks from public/tasks.json, persists annotations to Neon Postgres."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DATABASE_URL = os.environ.get("DATABASE_URL", "")

REPO_ROOT = Path(__file__).resolve().parent.parent
TASKS_PATH = REPO_ROOT / "public" / "tasks.json"

app = FastAPI(title="audio-label", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _create_schema() -> None:
    if not DATABASE_URL:
        return
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS annotations (
                    id            SERIAL PRIMARY KEY,
                    submitted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    export_version INTEGER NOT NULL,
                    task_id       TEXT NOT NULL,
                    annotation    JSONB,
                    meta          JSONB NOT NULL DEFAULT '{}'
                );
            """)
        conn.commit()


@app.on_event("startup")
def startup() -> None:
    _create_schema()


@contextmanager
def _db():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()


class AnnotationIn(BaseModel):
    export_version: int = Field(..., ge=1)
    task_id: str
    annotation: dict | list | str | None = None
    meta: dict = Field(default_factory=dict)


def _load_tasks_raw() -> dict:
    if not TASKS_PATH.is_file():
        raise HTTPException(
            status_code=500,
            detail=f"Missing tasks file: {TASKS_PATH}",
        )
    with TASKS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/tasks")
def list_tasks() -> dict:
    data = _load_tasks_raw()
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        raise HTTPException(status_code=500, detail="tasks.json must contain a 'tasks' array")
    return {"tasks": tasks}


@app.get("/api/progress")
def get_progress() -> dict:
    if not DATABASE_URL:
        return {"completed_task_ids": []}
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT task_id FROM annotations ORDER BY task_id;")
            rows = cur.fetchall()
    return {"completed_task_ids": [row[0] for row in rows]}


@app.post("/api/annotations")
def save_annotation(body: AnnotationIn) -> dict:
    task_ids = {t.get("id") for t in _load_tasks_raw().get("tasks", []) if isinstance(t, dict)}
    if body.task_id not in task_ids:
        raise HTTPException(status_code=400, detail=f"Unknown task_id: {body.task_id!r}")

    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="DATABASE_URL not configured")

    annotation_json = json.dumps(body.annotation) if body.annotation is not None else None
    meta_json = json.dumps(body.meta)

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO annotations (submitted_at, export_version, task_id, annotation, meta)
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
                RETURNING id;
                """,
                (
                    datetime.now(timezone.utc),
                    body.export_version,
                    body.task_id,
                    annotation_json,
                    meta_json,
                ),
            )
            row_id = cur.fetchone()[0]
        conn.commit()

    return {"ok": True, "id": row_id}
