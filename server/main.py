"""Lightweight API: serves tasks from public/tasks.json, appends annotations to data/annotations.jsonl."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parent.parent
TASKS_PATH = REPO_ROOT / "public" / "tasks.json"
DATA_DIR = REPO_ROOT / "data"
ANNOTATIONS_PATH = DATA_DIR / "annotations.jsonl"

app = FastAPI(title="audio-label", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.post("/api/annotations")
def save_annotation(body: AnnotationIn) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    task_ids = {t.get("id") for t in _load_tasks_raw().get("tasks", []) if isinstance(t, dict)}
    if body.task_id not in task_ids:
        raise HTTPException(status_code=400, detail=f"Unknown task_id: {body.task_id!r}")

    line = {
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "export_version": body.export_version,
        "task_id": body.task_id,
        "annotation": body.annotation,
        "meta": body.meta,
    }
    with ANNOTATIONS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return {"ok": True, "path": str(ANNOTATIONS_PATH.relative_to(REPO_ROOT))}
