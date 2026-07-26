from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from control_center.checks.cron_jobs import (
    CronMutationError,
    get_cron_jobs,
    pause_job,
    resume_job,
    update_schedule,
)
from control_center.core.auth import require_admin

router = APIRouter()


def _workspace_root() -> Path:
    return Path(os.environ.get("WORKSPACE_ROOT", "/workspace"))


def _spool_path() -> Path:
    return Path(os.environ.get("CRONTAB_SPOOL_PATH", "/var/spool/cron/crontabs/manish"))


class ScheduleUpdate(BaseModel):
    schedule: str


@router.get("/cron/jobs")
def cron_jobs() -> JSONResponse:
    """Read-only status for the 4 known host-crontab jobs. Open to everyone."""
    return JSONResponse({"jobs": get_cron_jobs(_workspace_root(), _spool_path())})


@router.post("/cron/jobs/{job_id}/pause")
def cron_job_pause(job_id: str, _admin: dict = Depends(require_admin)) -> JSONResponse:
    try:
        result = pause_job(_spool_path(), job_id)
    except CronMutationError as e:
        return JSONResponse({"error": str(e)}, status_code=e.status_code)
    return JSONResponse(result)


@router.post("/cron/jobs/{job_id}/resume")
def cron_job_resume(job_id: str, _admin: dict = Depends(require_admin)) -> JSONResponse:
    try:
        result = resume_job(_spool_path(), job_id)
    except CronMutationError as e:
        return JSONResponse({"error": str(e)}, status_code=e.status_code)
    return JSONResponse(result)


@router.put("/cron/jobs/{job_id}/schedule")
def cron_job_schedule(
    job_id: str, body: ScheduleUpdate, _admin: dict = Depends(require_admin),
) -> JSONResponse:
    try:
        result = update_schedule(_spool_path(), job_id, body.schedule)
    except CronMutationError as e:
        return JSONResponse({"error": str(e)}, status_code=e.status_code)
    return JSONResponse(result)
