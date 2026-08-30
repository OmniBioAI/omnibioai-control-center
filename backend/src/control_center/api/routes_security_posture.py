"""Read-only Security Posture evidence report endpoint."""

from __future__ import annotations

import logging

from control_center.core.auth import require_permission
from control_center.security_posture_backend import load_security_posture_report
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

router = APIRouter()
log = logging.getLogger(__name__)
_require_manage_all_orgs = require_permission("manage_all_orgs")


@router.get("/security-posture")
def security_posture(_admin: dict = Depends(_require_manage_all_orgs)) -> JSONResponse:  # noqa: B008
    try:
        report = load_security_posture_report()
        return JSONResponse(report.as_dict())
    except Exception:  # noqa: BLE001 - endpoint must fail safely for assembly errors
        log.warning("Security posture assembly unavailable")
        return JSONResponse(
            {"status": "STATUS_UNAVAILABLE", "message": "Security posture data is unavailable."},
            status_code=503,
        )
