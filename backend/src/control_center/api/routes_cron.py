from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from control_center.checks.cron_jobs import get_cron_jobs

router = APIRouter()


@router.get("/cron/jobs")
def cron_jobs() -> JSONResponse:
    """Read-only status for the 4 known host-crontab jobs. Open to everyone."""
    workspace = Path(os.environ.get("WORKSPACE_ROOT", "/workspace"))
    return JSONResponse({"jobs": get_cron_jobs(workspace)})
