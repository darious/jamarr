from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg
from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db import get_db
from app.api.deps import get_current_user_jwt
from app.scheduler import Scheduler, get_job_definitions, JOB_DEFINITIONS


router = APIRouter(
    prefix="/api/scheduler",
    tags=["scheduler"],
    dependencies=[Depends(get_current_user_jwt)],
)


class CreateTaskRequest(BaseModel):
    job_key: str
    cron: str
    enabled: bool = True


class UpdateTaskRequest(BaseModel):
    cron: Optional[str] = None
    enabled: Optional[bool] = None


def _task_row_to_dict(row: asyncpg.Record) -> Dict[str, Any]:
    job = JOB_DEFINITIONS.get(row["job_key"])
    return {
        "id": row["id"],
        "job_key": row["job_key"],
        "job": {
            "key": row["job_key"],
            "name": job.name,
            "description": job.description,
        }
        if job
        else None,
        "cron": row["cron"],
        "timezone": row["timezone"],
        "enabled": row["enabled"],
        "last_run_at": row["last_run_at"],
        "next_run_at": row["next_run_at"],
        "last_status": row["last_status"],
        "last_error": row["last_error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _validate_cron(expr: str) -> None:
    try:
        croniter(expr, datetime.now(timezone.utc))
    except (ValueError, KeyError):
        raise HTTPException(status_code=400, detail="Invalid cron expression")


def _next_run(expr: str) -> datetime:
    return croniter(expr, datetime.now(timezone.utc)).get_next(datetime)


@router.get("/jobs")
async def list_jobs() -> List[Dict[str, str]]:
    return get_job_definitions()


@router.get("/tasks")
async def list_tasks():
    async for db in get_db():
        rows = await db.fetch(
            """
            SELECT id, job_key, cron, timezone, enabled, last_run_at, next_run_at,
                   last_status, last_error, created_at, updated_at
            FROM scheduled_task
            ORDER BY created_at DESC, id DESC
            """
        )
        scheduler = Scheduler.get_instance()
        tasks = []
        for row in rows:
            if row["last_status"] == "running" and not scheduler.is_running(row["id"]):
                await db.execute(
                    """
                    UPDATE scheduled_task
                    SET last_status = $1,
                        last_error = $2,
                        updated_at = NOW()
                    WHERE id = $3
                    """,
                    "interrupted",
                    "Scheduler restart or task ended unexpectedly",
                    row["id"],
                )
                await db.execute(
                    """
                    UPDATE scheduled_task_run
                    SET finished_at = NOW(),
                        status = $1,
                        error = $2,
                        duration_ms = COALESCE(duration_ms, 0)
                    WHERE task_id = $3 AND status = 'running'
                    """,
                    "interrupted",
                    "Scheduler restart or task ended unexpectedly",
                    row["id"],
                )
                row = dict(row)
                row["last_status"] = "interrupted"
                row["last_error"] = "Scheduler restart or task ended unexpectedly"
            tasks.append(_task_row_to_dict(row))
        return tasks
    return []


@router.post("/tasks")
async def create_task(payload: CreateTaskRequest):
    if payload.job_key not in JOB_DEFINITIONS:
        raise HTTPException(status_code=400, detail="Unknown job type")
    _validate_cron(payload.cron)
    next_run = _next_run(payload.cron) if payload.enabled else None
    async for db in get_db():
        row = await db.fetchrow(
            """
            INSERT INTO scheduled_task (job_key, cron, timezone, enabled, next_run_at)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, job_key, cron, timezone, enabled, last_run_at, next_run_at,
                      last_status, last_error, created_at, updated_at
            """,
            payload.job_key,
            payload.cron,
            "UTC",
            payload.enabled,
            next_run,
        )
        return _task_row_to_dict(row)
    raise HTTPException(status_code=500, detail="Failed to create task")


@router.patch("/tasks/{task_id}")
async def update_task(task_id: int, payload: UpdateTaskRequest):
    async for db in get_db():
        current = await db.fetchrow(
            """
            SELECT id, job_key, cron, timezone, enabled, last_run_at, next_run_at,
                   last_status, last_error, created_at, updated_at
            FROM scheduled_task
            WHERE id = $1
            """,
            task_id,
        )
        if not current:
            raise HTTPException(status_code=404, detail="Task not found")

        cron_expr = payload.cron or current["cron"]
        if payload.cron:
            _validate_cron(payload.cron)

        enabled = payload.enabled if payload.enabled is not None else current["enabled"]
        next_run = _next_run(cron_expr) if enabled else None

        row = await db.fetchrow(
            """
            UPDATE scheduled_task
            SET cron = $1,
                enabled = $2,
                next_run_at = $3,
                updated_at = NOW()
            WHERE id = $4
            RETURNING id, job_key, cron, timezone, enabled, last_run_at, next_run_at,
                      last_status, last_error, created_at, updated_at
            """,
            cron_expr,
            enabled,
            next_run,
            task_id,
        )
        return _task_row_to_dict(row)
    raise HTTPException(status_code=500, detail="Failed to update task")


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int):
    async for db in get_db():
        result = await db.execute(
            "DELETE FROM scheduled_task WHERE id = $1", task_id
        )
        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="Task not found")
        return {"ok": True}
    raise HTTPException(status_code=500, detail="Failed to delete task")


@router.post("/tasks/{task_id}/run")
async def run_task(task_id: int):
    async for db in get_db():
        exists = await db.fetchval(
            "SELECT 1 FROM scheduled_task WHERE id = $1", task_id
        )
        if not exists:
            raise HTTPException(status_code=404, detail="Task not found")
    scheduler = Scheduler.get_instance()
    ok = await scheduler.run_task_now(task_id)
    if not ok:
        raise HTTPException(status_code=409, detail="Task is already running")
    return {"ok": True}


@router.post("/tasks/{task_id}/stop")
async def stop_task(task_id: int):
    async for db in get_db():
        exists = await db.fetchval(
            "SELECT 1 FROM scheduled_task WHERE id = $1", task_id
        )
        if not exists:
            raise HTTPException(status_code=404, detail="Task not found")
    scheduler = Scheduler.get_instance()
    ok = await scheduler.stop_task(task_id)
    if not ok:
        raise HTTPException(status_code=409, detail="Task is not running")
    return {"ok": True}


@router.get("/tasks/{task_id}/runs")
async def list_runs(task_id: int):
    async for db in get_db():
        rows = await db.fetch(
            """
            SELECT id, task_id, started_at, finished_at, status, error, duration_ms
            FROM scheduled_task_run
            WHERE task_id = $1
            ORDER BY started_at DESC
            LIMIT 50
            """,
            task_id,
        )
        return [dict(row) for row in rows]
    return []
