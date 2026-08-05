from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

# PR11.5.6 (Admin Console Security UI). Same reasoning as
# routes_org_sso_proxy.py (PR11.3) before it: no authorization decision
# is made here -- omnibioai-auth's own require_org_permission_or_
# platform_admin(MANAGE_SSO) (the 3 CRUD routes) and require_permission
# (MANAGE_ALL_ORGS) (the 2 override routes) decide every request, both
# from PR11.5.5 and unmodified by this PR. Pure relay: never inspects,
# caches, or logs the request/response bodies it forwards. See
# docs/pr11-5-6-security-ui-discovery.md SS6.3 for why this file (wiring,
# not IAM logic) is in this PR's scope despite the task's "no backend
# changes" default.
router = APIRouter()

IAM_URL = os.environ.get("IAM_URL", "http://auth-service:8001")


async def _proxy(method: str, path: str, request: Request) -> Response:
    body = await request.body()
    headers = {"Content-Type": "application/json"}
    auth_header = request.headers.get("authorization")
    if auth_header:
        headers["Authorization"] = auth_header

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.request(
                method,
                f"{IAM_URL}{path}",
                params=request.query_params,
                content=body if method in ("POST", "PATCH", "PUT") else None,
                headers=headers,
            )
    except httpx.RequestError as e:
        return JSONResponse(
            {"error": f"auth-service unreachable: {type(e).__name__}: {e}"}, status_code=503,
        )

    # No route in this file returns 204 today (unlike routes_org_sso_
    # proxy.py's DELETE /orgs/{org_id}/sso) -- omnibioai-auth's own
    # POST/GET/PATCH /orgs/{org_id}/mfa-policy and .../override routes
    # all return a body. Kept anyway, same defensive shape as every
    # other proxy file, in case that ever changes.
    if not r.content:
        return Response(status_code=r.status_code)

    try:
        payload = r.json()
    except ValueError:
        payload = {"error": "auth-service returned a non-JSON response"}
    return JSONResponse(payload, status_code=r.status_code)


# ---------------- Org-scoped MFA policy configuration ----------------


@router.get("/orgs/{org_id}/mfa-policy")
async def get_org_mfa_policy_proxy(org_id: int, request: Request) -> Response:
    return await _proxy("GET", f"/orgs/{org_id}/mfa-policy", request)


@router.post("/orgs/{org_id}/mfa-policy")
async def create_org_mfa_policy_proxy(org_id: int, request: Request) -> Response:
    return await _proxy("POST", f"/orgs/{org_id}/mfa-policy", request)


@router.patch("/orgs/{org_id}/mfa-policy")
async def update_org_mfa_policy_proxy(org_id: int, request: Request) -> Response:
    return await _proxy("PATCH", f"/orgs/{org_id}/mfa-policy", request)


# ---------------- Break-glass override (global-admin only) ----------------


@router.post("/orgs/{org_id}/mfa-policy/override")
async def override_org_mfa_policy_proxy(org_id: int, request: Request) -> Response:
    return await _proxy("POST", f"/orgs/{org_id}/mfa-policy/override", request)


@router.delete("/orgs/{org_id}/mfa-policy/override")
async def clear_org_mfa_policy_override_proxy(org_id: int, request: Request) -> Response:
    return await _proxy("DELETE", f"/orgs/{org_id}/mfa-policy/override", request)
