"""GET /compliance/hipaa-report[/pdf|/csv] -- Basic HIPAA Compliance
Report (OmniBioAI Studio v0.8.0). Platform_admin-only for this version:
org_admin scoping is deferred to v0.9.0 -- two of the four sections'
sources (login events, the security-audit deny stream) have no org-scoped
read path today, and building one is a real backend change in
omnibioai-auth, not something this report's own router can paper over
(see compliance/service.py's module docstring for the full reasoning).

Every route: 1) requires manage_all_orgs (the same platform-admin bypass
permission every other /platform/* surface in this ecosystem already
uses -- auth/app/rbac.py::MANAGE_ALL_ORGS, reused verbatim, not
redefined); 2) reads-through the existing 1-hour-capable Redis cache
(analytics/cache.py -- this package doesn't own a second caching
mechanism); 3) delegates all aggregation to service.py -- no computation
happens in this file.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from control_center.analytics import cache
from control_center.compliance import service
from control_center.core.auth import require_permission

router = APIRouter(prefix="/compliance", tags=["compliance"])

# Same string omnibioai-auth's app/rbac.py::MANAGE_ALL_ORGS,
# omnibioai-billing's core/iam.py, and control-center's own
# analytics/permissions.py already check -- one ecosystem-wide meaning,
# not redefined per module.
MANAGE_ALL_ORGS = "manage_all_orgs"

_CACHE_TTL_SECONDS = 3600  # task brief: "Cache report 1hr (expensive query)"

_require_platform_admin = require_permission(MANAGE_ALL_ORGS)


def _cache_key(organization_id: int, from_date: date, to_date: date) -> str:
    return f"compliance:hipaa-report:{organization_id}:{from_date.isoformat()}:{to_date.isoformat()}"


def _generated_by(payload: dict) -> str:
    return payload.get("email") or payload.get("sub") or "unknown"


def _validate_range(from_date: date, to_date: date) -> None:
    if from_date > to_date:
        raise HTTPException(400, "from_date must be on or before to_date")


async def _build_cached_report(
    *, org_id: int, from_date: date, to_date: date, generated_by: str, authorization: Optional[str],
) -> dict:
    key = _cache_key(org_id, from_date, to_date)
    return await cache.get_or_set_async(
        key,
        "hipaa_report",
        lambda: service.build_report(
            organization_id=org_id, from_date=from_date, to_date=to_date,
            generated_by=generated_by, authorization=authorization,
        ),
        ttl=_CACHE_TTL_SECONDS,
    )


@router.get("/hipaa-report")
async def hipaa_report(
    from_date: date = Query(...),
    to_date: date = Query(...),
    org_id: int = Query(...),
    authorization: Optional[str] = Header(default=None),
    admin: dict = Depends(_require_platform_admin),
) -> dict:
    _validate_range(from_date, to_date)
    return await _build_cached_report(
        org_id=org_id, from_date=from_date, to_date=to_date,
        generated_by=_generated_by(admin), authorization=authorization,
    )
