from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from control_center.checks.cron_jobs import (
    CronMutationError,
    get_cron_jobs,
    get_job_log,
    pause_job,
    resume_job,
    update_schedule,
)
from control_center.core.auth import require_permission

router = APIRouter()


def _workspace_root() -> Path:
    return Path(os.environ.get("WORKSPACE_ROOT", "/workspace"))


def _spool_path() -> Path:
    return Path(os.environ.get("CRONTAB_SPOOL_PATH", "/var/spool/cron/crontabs/manish"))


class ScheduleUpdate(BaseModel):
    schedule: str


@router.get("/cron/jobs")
def cron_jobs(_admin: dict = Depends(require_permission("platform.manage_infra"))) -> JSONResponse:
    """Read-only status for the 15 known host-crontab jobs.

    Gated: previously open to everyone -- confirmed live-reachable with no
    auth via control.omnibioai.org routing directly to this backend,
    bypassing nginx-router's auth_request gate entirely. No legitimate
    public use case for exposing the host crontab job list."""
    return JSONResponse({"jobs": get_cron_jobs(_workspace_root(), _spool_path())})

@router.get("/cron/jobs/{job_id}/log")
def cron_job_log(
    job_id: str, lines: int = 100, _admin: dict = Depends(require_permission("platform.manage_infra")),
) -> JSONResponse:
    """Read-only tail of a job's log file.

    Gated: previously open to everyone, same as GET /cron/jobs above --
    an arbitrary log-file tail (up to 1000 lines) with no auth at all."""
    lines = max(1, min(lines, 1000))  # clamp to a sane range
    try:
        result = get_job_log(_workspace_root(), job_id, lines)
    except CronMutationError as e:
        return JSONResponse({"error": str(e)}, status_code=e.status_code)
    return JSONResponse(result)

@router.post("/cron/jobs/{job_id}/pause")
def cron_job_pause(job_id: str, _admin: dict = Depends(require_permission("platform.manage_cron"))) -> JSONResponse:
    # AUDIT_EVENT integration point: PR3D leaves this a comment, not a call
    # -- IAM's persistent audit ledger (PR9) has no client library this
    # repo can import yet. Once one exists, emit here with actor=_admin["sub"],
    # action="cron.pause", target=job_id.
    try:
        result = pause_job(_spool_path(), job_id)
    except CronMutationError as e:
        return JSONResponse({"error": str(e)}, status_code=e.status_code)
    return JSONResponse(result)


@router.post("/cron/jobs/{job_id}/resume")
def cron_job_resume(job_id: str, _admin: dict = Depends(require_permission("platform.manage_cron"))) -> JSONResponse:
    # AUDIT_EVENT integration point: see cron_job_pause above --
    # actor=_admin["sub"], action="cron.resume", target=job_id.
    try:
        result = resume_job(_spool_path(), job_id)
    except CronMutationError as e:
        return JSONResponse({"error": str(e)}, status_code=e.status_code)
    return JSONResponse(result)


@router.put("/cron/jobs/{job_id}/schedule")
def cron_job_schedule(
    job_id: str, body: ScheduleUpdate, _admin: dict = Depends(require_permission("platform.manage_cron")),
) -> JSONResponse:
    # AUDIT_EVENT integration point: see cron_job_pause above --
    # actor=_admin["sub"], action="cron.schedule_update", target=job_id,
    # detail=body.schedule.
    try:
        result = update_schedule(_spool_path(), job_id, body.schedule)
    except CronMutationError as e:
        return JSONResponse({"error": str(e)}, status_code=e.status_code)
    return JSONResponse(result)
