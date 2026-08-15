"""GET/POST/PATCH /hipaa-compliance/changes[...] -- persistent history of
HIPAA-relevant engineering changes/releases for the Admin Console's HIPAA
Compliance Report (V1).

Every route requires manage_all_orgs -- the same platform-admin
permission GET /compliance/hipaa-report (compliance/router.py, HIPAA
Basic Compliance Report v0.8.0) already uses, reused verbatim, not
redefined. Reads are gated too, not just writes: a compliance record can
reference a commit SHA, a PR number, or an internal component name, and
this repo's own posture elsewhere is "administrative audit/compliance
data is platform_admin-only, full stop" (see routes_audit_proxy.py's own
docstring for the identical reasoning on GET /platform/audit-events) --
there's no argument for a narrower gate here that doesn't apply equally
there.

No automatic producer in V1: this is a directly-written CRUD resource
(POST/PATCH by a platform_admin, plus the one-time seed in seed.py for
already-completed changes), not a consumer of the audit:events stream.
Investigated and deliberately deferred, not overlooked -- this
ecosystem's six real audit:events producers emit access/security events
(login, role change, API key created, ...), not "a PR merged" events,
and there is no CI/git webhook integration anywhere in this ecosystem
today that could emit one without a separate, out-of-scope integration
project.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from control_center.core.auth import require_permission
from control_center.hipaa_compliance import service
from control_center.hipaa_compliance.db import get_db
from control_center.hipaa_compliance.schemas import (
    HipaaComplianceChangeCreate,
    HipaaComplianceChangeListResponse,
    HipaaComplianceChangeOut,
    HipaaComplianceChangeUpdate,
    HipaaComplianceSummaryOut,
)

router = APIRouter(prefix="/hipaa-compliance/changes", tags=["hipaa-compliance"])

MANAGE_ALL_ORGS = "manage_all_orgs"
_require_platform_admin = require_permission(MANAGE_ALL_ORGS)


@router.get("/summary", response_model=HipaaComplianceSummaryOut)
def get_summary(
    db: Session = Depends(get_db),  # noqa: B008 -- FastAPI's own documented dependency-injection pattern
    _admin: dict = Depends(_require_platform_admin),  # noqa: B008
) -> HipaaComplianceSummaryOut:
    return service.build_summary(db)


# Registered before "/{change_id}" -- FastAPI/Starlette matches routes in
# registration order, so a literal "/summary" path segment must be
# declared first or it would be swallowed by the "/{change_id}" path
# parameter below and 404 as "no change with id 'summary'".
@router.get("", response_model=HipaaComplianceChangeListResponse)
def list_changes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    control_category: str | None = Query(None),
    repository: str | None = Query(None),
    db: Session = Depends(get_db),  # noqa: B008
    _admin: dict = Depends(_require_platform_admin),  # noqa: B008
) -> HipaaComplianceChangeListResponse:
    rows, total = service.list_changes(
        db, page=page, page_size=page_size,
        status=status, control_category=control_category, repository=repository,
    )
    total_pages = (total + page_size - 1) // page_size if total else 0
    return HipaaComplianceChangeListResponse(
        items=rows, total=total, page=page, page_size=page_size, total_pages=total_pages,
    )


@router.get("/{change_id}", response_model=HipaaComplianceChangeOut)
def get_change(
    change_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    _admin: dict = Depends(_require_platform_admin),  # noqa: B008
) -> HipaaComplianceChangeOut:
    try:
        return service.get_change(db, change_id)
    except service.ChangeNotFoundError:
        raise HTTPException(404, f"No HIPAA compliance change with id {change_id!r}")


@router.post("", response_model=HipaaComplianceChangeOut, status_code=201)
def create_change(
    payload: HipaaComplianceChangeCreate,
    db: Session = Depends(get_db),  # noqa: B008
    _admin: dict = Depends(_require_platform_admin),  # noqa: B008
) -> HipaaComplianceChangeOut:
    try:
        return service.create_change(db, payload)
    except service.ChangeAlreadyExistsError:
        raise HTTPException(409, f"A HIPAA compliance change with id {payload.change_id!r} already exists")


@router.patch("/{change_id}", response_model=HipaaComplianceChangeOut)
def update_change(
    change_id: str,
    payload: HipaaComplianceChangeUpdate,
    db: Session = Depends(get_db),  # noqa: B008
    _admin: dict = Depends(_require_platform_admin),  # noqa: B008
) -> HipaaComplianceChangeOut:
    try:
        return service.update_change(db, change_id, payload)
    except service.ChangeNotFoundError:
        raise HTTPException(404, f"No HIPAA compliance change with id {change_id!r}")
