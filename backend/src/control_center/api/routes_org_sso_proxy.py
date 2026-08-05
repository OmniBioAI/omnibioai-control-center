from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

# PR11.3 (Enterprise SSO Management UI). Same reasoning as
# routes_org_proxy.py (PR2), routes_role_proxy.py (PR3B), and
# routes_team_proxy.py (PR3C) before it: no authorization decision is
# made here -- omnibioai-auth's own require_org_permission_or_platform_
# admin(MANAGE_SSO) (the 4 CRUD routes) and require_permission
# (OVERRIDE_SSO_ENFORCEMENT) (the 2 override routes) decide every
# request, both pre-existing and unmodified by this PR. This file is a
# pure relay: it never inspects, caches, or logs the request/response
# bodies it forwards, which matters here specifically because those
# bodies carry client_secret on the way in -- see this PR's own docs/
# admin-console-pr11-sso-management.md for the full secret-handling
# note.
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

    # DELETE /orgs/{org_id}/sso succeeds with 204 and an empty body --
    # same case routes_team_proxy.py's/routes_role_proxy.py's _proxy
    # already handle for their own DELETE routes; r.json() on an empty
    # body raises, so the empty body is preserved faithfully instead of
    # inventing a fake JSON payload for it.
    if not r.content:
        return Response(status_code=r.status_code)

    try:
        payload = r.json()
    except ValueError:
        payload = {"error": "auth-service returned a non-JSON response"}
    return JSONResponse(payload, status_code=r.status_code)


# ---------------- Org-scoped SSO configuration ----------------


@router.get("/orgs/{org_id}/sso")
async def get_org_sso_proxy(org_id: int, request: Request) -> Response:
    return await _proxy("GET", f"/orgs/{org_id}/sso", request)


@router.post("/orgs/{org_id}/sso")
async def create_org_sso_proxy(org_id: int, request: Request) -> Response:
    return await _proxy("POST", f"/orgs/{org_id}/sso", request)


@router.patch("/orgs/{org_id}/sso")
async def update_org_sso_proxy(org_id: int, request: Request) -> Response:
    return await _proxy("PATCH", f"/orgs/{org_id}/sso", request)


@router.delete("/orgs/{org_id}/sso")
async def delete_org_sso_proxy(org_id: int, request: Request) -> Response:
    return await _proxy("DELETE", f"/orgs/{org_id}/sso", request)


# ---------------- Break-glass override (global-admin only) ----------------


@router.post("/orgs/{org_id}/sso/override")
async def override_org_sso_proxy(org_id: int, request: Request) -> Response:
    return await _proxy("POST", f"/orgs/{org_id}/sso/override", request)


@router.delete("/orgs/{org_id}/sso/override")
async def clear_org_sso_override_proxy(org_id: int, request: Request) -> Response:
    return await _proxy("DELETE", f"/orgs/{org_id}/sso/override", request)
