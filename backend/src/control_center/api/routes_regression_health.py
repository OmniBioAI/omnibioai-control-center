"""Read-only regression certification status endpoint."""

from __future__ import annotations

import logging

from control_center.regression_health import (
    RegressionHealthUnavailable,
    load_regression_health,
)
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()
log = logging.getLogger(__name__)


@router.get("/regression-health")
def get_regression_health() -> JSONResponse:
    try:
        return JSONResponse(load_regression_health())
    except RegressionHealthUnavailable as error:
        # The reason code is deliberately not accompanied by the path or the
        # underlying exception, which could disclose deployment information.
        log.warning("Regression health status unavailable: %s", error.code)
        return JSONResponse(
            {
                "status": "STATUS_UNAVAILABLE",
                "message": "Regression health certification data is unavailable.",
            },
            status_code=503,
        )
