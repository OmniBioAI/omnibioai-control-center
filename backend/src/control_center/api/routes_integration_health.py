"""Protected, read-only Integration Health report endpoint."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from control_center.integration_health_adapter import (
    IntegrationInventoryUnavailable,
    build_integration_health_report,
)
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()
log = logging.getLogger(__name__)


def _unavailable_response() -> JSONResponse:
    return JSONResponse(
        {"status": "STATUS_UNAVAILABLE", "message": "Integration health data is unavailable."},
        status_code=503,
    )


@router.get("/integration-health")
def get_integration_health() -> JSONResponse:
    try:
        report = build_integration_health_report(generated_at=datetime.now(UTC))
    except IntegrationInventoryUnavailable as error:
        log.warning("Integration health status unavailable: %s", error.code)
        return _unavailable_response()
    return JSONResponse(report)
