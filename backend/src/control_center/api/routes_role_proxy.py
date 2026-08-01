from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

# Phase 3 PR3B (Roles & Permissions Management). Same reasoning as
# routes_org_proxy.py (PR2) and routes_user_proxy.py (PR3A) before it: no
# authorization decision is made here -- omnibioai-auth's own
# require_permission(MANAGE_ALL_ORGS) and
# require_org_permission_or_platform_admin(MANAGE_ORG) (Phase 3 PR0.4)
# decide every request. A separate file from both of those, not an
# extension of either -- same "one concern per proxy file" choice they
# each already made, now applied a third time; this file happens to cover
# both a /platform/* surface and an /orgs/* surface because both are the
# same concern (roles), unlike organizations vs. users.
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

    # DELETE .../roles/{role_id} succeeds with 204 and an empty body --
    # unlike every route routes_org_proxy.py/routes_user_proxy.py proxy,
    # this file is the first to relay a no-content response. r.json() on
    # an empty body raises; preserve the empty body faithfully instead of
    # inventing a fake JSON payload for it.
    if not r.content:
        return Response(status_code=r.status_code)

    try:
        payload = r.json()
    except ValueError:
        payload = {"error": "auth-service returned a non-JSON response"}
    return JSONResponse(payload, status_code=r.status_code)


# ---------------- Platform-admin global roles (Phase 3 PR3B) ----------------


@router.get("/platform/roles")
async def list_platform_roles_proxy(request: Request) -> Response:
    return await _proxy("GET", "/platform/roles", request)


@router.get("/platform/users/{user_id}/roles")
async def get_platform_user_roles_proxy(user_id: int, request: Request) -> Response:
    return await _proxy("GET", f"/platform/users/{user_id}/roles", request)


@router.post("/platform/users/{user_id}/roles")
async def assign_platform_user_role_proxy(user_id: int, request: Request) -> Response:
    return await _proxy("POST", f"/platform/users/{user_id}/roles", request)


@router.delete("/platform/users/{user_id}/roles/{role_id}")
async def remove_platform_user_role_proxy(user_id: int, role_id: int, request: Request) -> Response:
    return await _proxy("DELETE", f"/platform/users/{user_id}/roles/{role_id}", request)


# ---------------- Org-scoped roles (Phase 3 PR3B) ----------------


@router.get("/orgs/{org_id}/roles")
async def list_org_roles_proxy(org_id: int, request: Request) -> Response:
    return await _proxy("GET", f"/orgs/{org_id}/roles", request)


@router.get("/orgs/{org_id}/members/{user_id}/roles")
async def get_org_member_roles_proxy(org_id: int, user_id: int, request: Request) -> Response:
    return await _proxy("GET", f"/orgs/{org_id}/members/{user_id}/roles", request)


@router.post("/orgs/{org_id}/members/{user_id}/roles")
async def assign_org_member_role_proxy(org_id: int, user_id: int, request: Request) -> Response:
    return await _proxy("POST", f"/orgs/{org_id}/members/{user_id}/roles", request)


@router.delete("/orgs/{org_id}/members/{user_id}/roles/{role_id}")
async def remove_org_member_role_proxy(org_id: int, user_id: int, role_id: int, request: Request) -> Response:
    return await _proxy("DELETE", f"/orgs/{org_id}/members/{user_id}/roles/{role_id}", request)
