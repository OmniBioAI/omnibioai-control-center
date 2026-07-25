from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from control_center.checks.activity import get_activity_status
from control_center.checks.audit_trail import get_audit_trail
from control_center.checks.celery_status import get_celery_status
from control_center.checks.database_status import get_database_status
from control_center.checks.gateway_traffic import get_gateway_traffic
from control_center.checks.gpu import get_gpu_status
from control_center.checks.image_freshness import get_image_freshness
from control_center.checks.integrity import run_integrity_checks
from control_center.checks.license_status import get_license_status
from control_center.checks.usage_status import get_usage_status
from control_center.core.settings import load_settings

router = APIRouter()


@router.get("/gpu")
def gpu() -> JSONResponse:
    return JSONResponse(get_gpu_status())


@router.get("/celery")
def celery_status() -> JSONResponse:
    return JSONResponse(get_celery_status())


@router.get("/database")
def database_status() -> JSONResponse:
    return JSONResponse(get_database_status())


@router.get("/image-freshness")
def image_freshness() -> JSONResponse:
    return JSONResponse(get_image_freshness())


@router.get("/license")
def license_status() -> JSONResponse:
    return JSONResponse(get_license_status())


@router.get("/usage")
def usage_status() -> JSONResponse:
    return JSONResponse(get_usage_status())


@router.get("/gateway-traffic")
def gateway_traffic() -> JSONResponse:
    return JSONResponse(get_gateway_traffic())


@router.get("/audit-trail")
def audit_trail() -> JSONResponse:
    return JSONResponse(get_audit_trail())


@router.get("/activity")
def activity() -> JSONResponse:
    return JSONResponse(get_activity_status())


@router.get("/integrity")
def integrity() -> JSONResponse:
    try:
        settings = load_settings()
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse({
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "checks": run_integrity_checks(settings),
    })
