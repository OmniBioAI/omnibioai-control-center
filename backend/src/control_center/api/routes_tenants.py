from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Literal

from control_center.core.auth import require_permission
from control_center.tenants import service

router = APIRouter(prefix="/admin/tenants", tags=["tenant-admin"], dependencies=[Depends(require_permission("manage_all_orgs"))])

class OverrideBody(BaseModel):
    allocated_bytes: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=500)
    expires_at: str | None = None

class ReasonBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)

class PlanGrantBody(BaseModel):
    plan_id: Literal["plus", "pro"]
    days: int | None = Field(default=None, ge=1, le=365)
    expires_at: str | None = None
    reason: str = Field(min_length=1, max_length=500)

def _raise(exc: service.UpstreamError):
    raise HTTPException(status_code=exc.status_code, detail=exc.detail, headers={"Retry-After": "2"} if exc.status_code == 503 else None)

@router.get("/summary")
async def tenant_summary(authorization: str | None = Header(None)):
    try: return await service.cached_summary(authorization)
    except service.UpstreamError as exc: _raise(exc)

@router.get("")
async def list_tenants(
    plan: str | None = None, plan_source: str | None = None, status: str | None = None, validity: str | None = None,
    storage_status: str | None = None, q: str | None = None, sort: str = "username",
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
    organization_id: int | None = Query(None, ge=1), user_status: str | None = None, role: str | None = None,
    authorization: str | None = Header(None),
):
    try:
        return await service.paginated_tenants(authorization, page=page, page_size=page_size,
            plan=plan, plan_source=plan_source, status=status, validity=validity,
            storage_status=storage_status, q=q, sort=sort, organization_id=organization_id,
            user_status=user_status, role=role)
    except service.UpstreamError as exc: _raise(exc)

@router.get("/{tenant_id}")
async def get_tenant(tenant_id: str, authorization: str | None = Header(None)):
    try: detail = await service.tenant_detail(tenant_id, authorization)
    except service.UpstreamError as exc: _raise(exc)
    if detail is None: raise HTTPException(404, "Tenant not found")
    return detail

@router.put("/{tenant_id}/storage-override")
async def set_override(tenant_id: str, body: OverrideBody, authorization: str | None = Header(None)):
    if not body.reason.strip(): raise HTTPException(422, "Reason is required")
    try:
        await service.mutate("PUT", tenant_id, "storage-override", body.model_dump(), authorization, "billing")
        detail = await service.tenant_detail(tenant_id, authorization)
    except service.UpstreamError as exc: _raise(exc)
    if detail is None: raise HTTPException(404, "Tenant not found")
    return detail

@router.delete("/{tenant_id}/storage-override")
async def clear_override(tenant_id: str, body: ReasonBody, authorization: str | None = Header(None)):
    if not body.reason.strip(): raise HTTPException(422, "Reason is required")
    try:
        await service.mutate("DELETE", tenant_id, "storage-override", body.model_dump(), authorization, "billing")
        detail = await service.tenant_detail(tenant_id, authorization)
    except service.UpstreamError as exc: _raise(exc)
    if detail is None: raise HTTPException(404, "Tenant not found")
    return detail

@router.post("/{tenant_id}/recompute-usage")
async def recompute_usage(tenant_id: str, body: ReasonBody, authorization: str | None = Header(None)):
    if not body.reason.strip(): raise HTTPException(422, "Reason is required")
    try:
        await service.mutate("POST", tenant_id, "recompute", body.model_dump(), authorization, "workbench")
        detail = await service.tenant_detail(tenant_id, authorization)
    except service.UpstreamError as exc: _raise(exc)
    if detail is None: raise HTTPException(404, "Tenant not found")
    return detail

@router.post("/{tenant_id}/plan-grant")
async def grant_promo_plan(tenant_id: str, body: PlanGrantBody, authorization: str | None = Header(None)):
    if not body.reason.strip(): raise HTTPException(422, "Reason is required")
    if (body.days is None) == (body.expires_at is None): raise HTTPException(422, "Provide exactly one of days or expires_at")
    try:
        await service.mutate("POST", tenant_id, "plan-grant", body.model_dump(), authorization, "billing")
        detail = await service.tenant_detail(tenant_id, authorization)
    except service.UpstreamError as exc: _raise(exc)
    if detail is None: raise HTTPException(404, "Tenant not found")
    return detail

@router.delete("/{tenant_id}/plan-grant")
async def revoke_promo_plan(tenant_id: str, body: ReasonBody, authorization: str | None = Header(None)):
    if not body.reason.strip(): raise HTTPException(422, "Reason is required")
    try:
        await service.mutate("DELETE", tenant_id, "plan-grant", body.model_dump(), authorization, "billing")
        detail = await service.tenant_detail(tenant_id, authorization)
    except service.UpstreamError as exc: _raise(exc)
    if detail is None: raise HTTPException(404, "Tenant not found")
    return detail
