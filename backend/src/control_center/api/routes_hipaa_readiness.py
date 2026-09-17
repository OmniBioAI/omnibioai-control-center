from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from control_center.core.auth import require_permission
from control_center.hipaa_compliance.db import get_db
from control_center.hipaa_compliance import readiness_service as service
from control_center.hipaa_compliance.readiness_schemas import (
    ControlCreate, ControlListResponse, ControlOut, ControlUpdate, EvidenceCreate, EvidenceOut,
    ExceptionCreate, ExceptionOut, HistoryOut, LegacyMappingOut, RiskCreate, RiskOut,
)

router = APIRouter(prefix="/hipaa-compliance", tags=["hipaa-readiness"])
MANAGE_ALL_ORGS = "manage_all_orgs"
_require_platform_admin = require_permission(MANAGE_ALL_ORGS)


@router.get("/controls", response_model=ControlListResponse)
def list_controls(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    domain: str | None = Query(None), implementation_status: str | None = Query(None),
    testing_status: str | None = Query(None), deployment_status: str | None = Query(None),
    operational_verification_status: str | None = Query(None), applicability_status: str | None = Query(None),
    db: Session = Depends(get_db), admin: dict = Depends(_require_platform_admin),
) -> ControlListResponse:
    rows, total = service.list_controls(
        db, page=page, page_size=page_size, domain=domain, implementation_status=implementation_status,
        testing_status=testing_status, deployment_status=deployment_status,
        operational_verification_status=operational_verification_status, applicability_status=applicability_status,
    )
    total_pages = (total + page_size - 1) // page_size if total else 0
    return ControlListResponse(
        items=[service.to_control_out(db, r) for r in rows], total=total, page=page, page_size=page_size, total_pages=total_pages,
    )


@router.post("/controls", response_model=ControlOut, status_code=201)
def create_control(
    payload: ControlCreate, db: Session = Depends(get_db), admin: dict = Depends(_require_platform_admin),
) -> ControlOut:
    try:
        row = service.create_control(db, payload, actor=service.actor_from_claims(admin))
    except service.ControlAlreadyExistsError:
        raise HTTPException(409, f"A HIPAA readiness control with key {payload.control_key!r} already exists")
    return service.to_control_out(db, row)


@router.get("/controls/{control_key}", response_model=ControlOut)
def get_control(
    control_key: str, db: Session = Depends(get_db), admin: dict = Depends(_require_platform_admin),
) -> ControlOut:
    try:
        return service.to_control_out(db, service.get_control(db, control_key))
    except service.ControlNotFoundError:
        raise HTTPException(404, f"No HIPAA readiness control with key {control_key!r}")


@router.patch("/controls/{control_key}", response_model=ControlOut)
def update_control(
    control_key: str, payload: ControlUpdate, db: Session = Depends(get_db), admin: dict = Depends(_require_platform_admin),
) -> ControlOut:
    try:
        row = service.update_control(db, control_key, payload, actor=service.actor_from_claims(admin))
    except service.ControlNotFoundError:
        raise HTTPException(404, f"No HIPAA readiness control with key {control_key!r}")
    return service.to_control_out(db, row)


@router.get("/controls/{control_key}/evidence", response_model=list[EvidenceOut])
def list_evidence(control_key: str, db: Session = Depends(get_db), admin: dict = Depends(_require_platform_admin)):
    try:
        return service.list_evidence(db, control_key)
    except service.ControlNotFoundError:
        raise HTTPException(404, f"No HIPAA readiness control with key {control_key!r}")


@router.post("/controls/{control_key}/evidence", response_model=EvidenceOut, status_code=201)
def create_evidence(control_key: str, payload: EvidenceCreate, db: Session = Depends(get_db), admin: dict = Depends(_require_platform_admin)):
    try:
        return service.create_evidence(db, control_key, payload, actor=service.actor_from_claims(admin))
    except service.ControlNotFoundError:
        raise HTTPException(404, f"No HIPAA readiness control with key {control_key!r}")


@router.get("/controls/{control_key}/risks", response_model=list[RiskOut])
def list_risks(control_key: str, state: str | None = Query(None), db: Session = Depends(get_db), admin: dict = Depends(_require_platform_admin)):
    try:
        return service.list_risks(db, control_key, state=state)
    except service.ControlNotFoundError:
        raise HTTPException(404, f"No HIPAA readiness control with key {control_key!r}")


@router.post("/controls/{control_key}/risks", response_model=RiskOut, status_code=201)
def create_risk(control_key: str, payload: RiskCreate, db: Session = Depends(get_db), admin: dict = Depends(_require_platform_admin)):
    try:
        return service.create_risk(db, control_key, payload, actor=service.actor_from_claims(admin))
    except service.ControlNotFoundError:
        raise HTTPException(404, f"No HIPAA readiness control with key {control_key!r}")


@router.get("/controls/{control_key}/exceptions", response_model=list[ExceptionOut])
def list_exceptions(control_key: str, db: Session = Depends(get_db), admin: dict = Depends(_require_platform_admin)):
    try:
        return service.list_exceptions(db, control_key)
    except service.ControlNotFoundError:
        raise HTTPException(404, f"No HIPAA readiness control with key {control_key!r}")


@router.post("/controls/{control_key}/exceptions", response_model=ExceptionOut, status_code=201)
def create_exception(control_key: str, payload: ExceptionCreate, db: Session = Depends(get_db), admin: dict = Depends(_require_platform_admin)):
    try:
        return service.create_exception(db, control_key, payload, actor=service.actor_from_claims(admin))
    except service.ControlNotFoundError:
        raise HTTPException(404, f"No HIPAA readiness control with key {control_key!r}")


@router.get("/history", response_model=list[HistoryOut])
def list_history(entity_type: str | None = Query(None), entity_id: str | None = Query(None), db: Session = Depends(get_db), admin: dict = Depends(_require_platform_admin)):
    return service.list_history(db, entity_type=entity_type, entity_id=entity_id)


@router.get("/legacy-mappings", response_model=list[LegacyMappingOut])
def list_legacy_mappings(db: Session = Depends(get_db), admin: dict = Depends(_require_platform_admin)):
    return service.list_legacy_mappings(db)
