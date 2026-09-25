from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
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
from control_center.core import public_cache, public_view
from control_center.core.auth import infra_viewer, require_permission
from control_center.core.settings import load_settings

router = APIRouter()

# Public Read-Only Control Center architecture: gpu/celery/database/
# image-freshness/usage/gateway-traffic/activity/integrity stay reachable
# without a login, but their raw check output is NOT all aggregate: it
# includes container, database and worker names, route inventories,
# filesystem paths and exception text. Each of those routes therefore
# returns its full output only to a caller holding platform.manage_infra
# (core.auth.infra_viewer) and the allowlisted, counts-only shape from
# core/public_view.py to everyone else. /usage already returns aggregates
# only. /license and /audit-trail are the two routes gated outright:
# /license returns real customer/user email addresses
# (checks/license_status.py's own SELECT email ... query) and /audit-trail
# returns a raw, individually-listed audit-event feed including per-event
# user_id (checks/audit_trail.py).
_require_manage_infra = require_permission("platform.manage_infra")

@router.get("/gpu")
def gpu(full: bool = Depends(infra_viewer)) -> JSONResponse:
    if full:
        return JSONResponse(get_gpu_status())
    return JSONResponse(public_cache.cached("gpu", lambda: public_view.public_gpu(get_gpu_status())))


@router.get("/celery")
def celery_status(full: bool = Depends(infra_viewer)) -> JSONResponse:
    if full:
        return JSONResponse(get_celery_status())
    return JSONResponse(public_cache.cached("celery_status", lambda: public_view.public_celery(get_celery_status())))


@router.get("/database")
def database_status(full: bool = Depends(infra_viewer)) -> JSONResponse:
    if full:
        return JSONResponse(get_database_status())
    return JSONResponse(public_cache.cached("database_status", lambda: public_view.public_database(get_database_status())))


@router.get("/image-freshness")
def image_freshness(full: bool = Depends(infra_viewer)) -> JSONResponse:
    if full:
        return JSONResponse(get_image_freshness())
    return JSONResponse(public_cache.cached("image_freshness", lambda: public_view.public_image_freshness(get_image_freshness())))


@router.get("/license")
def license_status(_admin: dict = Depends(_require_manage_infra)) -> JSONResponse:
    return JSONResponse(get_license_status())


@router.get("/usage")
def usage_status() -> JSONResponse:
    # Aggregates only, same for every caller -- cached (it scans run dirs).
    return JSONResponse(public_cache.cached("usage", get_usage_status))


@router.get("/gateway-traffic")
def gateway_traffic(full: bool = Depends(infra_viewer)) -> JSONResponse:
    if full:
        return JSONResponse(get_gateway_traffic())
    return JSONResponse(public_cache.cached("gateway_traffic", lambda: public_view.public_gateway_traffic(get_gateway_traffic())))


@router.get("/audit-trail")
def audit_trail(_admin: dict = Depends(_require_manage_infra)) -> JSONResponse:
    return JSONResponse(get_audit_trail())


@router.get("/activity")
def activity(full: bool = Depends(infra_viewer)) -> JSONResponse:
    if full:
        return JSONResponse(get_activity_status())
    return JSONResponse(public_cache.cached("activity", lambda: public_view.public_activity(get_activity_status())))


@router.get("/integrity")
def integrity(full: bool = Depends(infra_viewer)) -> JSONResponse:
    try:
        settings = load_settings()
    except FileNotFoundError as e:
        # The message names the settings path -- operators only.
        return JSONResponse({"error": str(e) if full else "integrity checks unavailable"}, status_code=500)
    if full:
        return JSONResponse({
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "checks": run_integrity_checks(settings),
        })
    return JSONResponse(public_cache.cached("integrity", lambda: {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        **public_view.public_integrity(run_integrity_checks(settings)),
    }))
