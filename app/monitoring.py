from collections import deque
import logging
from pathlib import Path
import time

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel

from app.api.deps import get_current_admin_user_jwt
from app.security import (
    get_client_ip,
    redact_secrets,
    safe_request_path,
    safe_user_agent,
    sanitize_log_value,
)

LOG_DIR = Path("cache/log")
LOG_FILES = {
    "security": "security.log",
    "access": "access.log",
    "backend": "backend.log",
    "player": "player.log",
    "lastfm": "lastfm.log",
    "scanner": "scanner.log",
    "upnp": "upnp.log",
    "frontend": "frontend.log",
}
MAX_LOG_LINES = 1000

router = APIRouter(
    prefix="/api/monitoring",
    dependencies=[Depends(get_current_admin_user_jwt)],
)


class LogFileInfo(BaseModel):
    key: str
    name: str
    exists: bool
    size_bytes: int
    modified_at: float | None


class MonitoringSummary(BaseModel):
    logs: list[LogFileInfo]
    alerts: list[str]


class LogResponse(BaseModel):
    key: str
    name: str
    lines: list[str]


def _resolve_log_file(key: str) -> Path:
    filename = LOG_FILES.get(key)
    if not filename:
        raise HTTPException(status_code=404, detail="Unknown log file")
    return LOG_DIR / filename


def tail_log_lines(path: Path, line_count: int) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        lines = deque(handle, maxlen=line_count)
    return [str(redact_secrets(line.rstrip("\n"))) for line in lines]


def recent_security_alerts(line_count: int = 20) -> list[str]:
    alerts: list[str] = []
    for line in tail_log_lines(LOG_DIR / LOG_FILES["security"], MAX_LOG_LINES):
        if "[WARNING]" in line or "[ERROR]" in line or "[CRITICAL]" in line:
            alerts.append(line)
    return alerts[-line_count:]


@router.get("/summary", response_model=MonitoringSummary)
async def monitoring_summary():
    logs: list[LogFileInfo] = []
    for key, filename in LOG_FILES.items():
        path = LOG_DIR / filename
        exists = path.exists()
        stat = path.stat() if exists else None
        logs.append(
            LogFileInfo(
                key=key,
                name=filename,
                exists=exists,
                size_bytes=stat.st_size if stat else 0,
                modified_at=stat.st_mtime if stat else None,
            )
        )
    return MonitoringSummary(logs=logs, alerts=recent_security_alerts())


@router.get("/logs", response_model=LogResponse)
async def monitoring_logs(
    file: str = Query("security"),
    lines: int = Query(200, ge=1, le=MAX_LOG_LINES),
):
    path = _resolve_log_file(file)
    return LogResponse(
        key=file,
        name=LOG_FILES[file],
        lines=tail_log_lines(path, lines),
    )


def configure_monitoring_middleware(app: FastAPI) -> None:
    access_logger = logging.getLogger("app.monitoring.access")

    @app.middleware("http")
    async def sanitized_access_log(request: Request, call_next):
        start = time.perf_counter()
        status_code = 500
        path = safe_request_path(request)
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            if path != "/api/player/state":
                duration_ms = (time.perf_counter() - start) * 1000
                access_logger.info(
                    "ip=%s method=%s path=%s status=%s duration_ms=%.1f user_agent=%s",
                    sanitize_log_value(get_client_ip(request), 80),
                    request.method,
                    path,
                    status_code,
                    duration_ms,
                    safe_user_agent(request),
                )
