from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

# Phase 3 PR3C (Teams Management). Same reasoning as routes_org_proxy.py
# (PR2), routes_user_proxy.py (PR3A), and routes_role_proxy.py (PR3B)
# before it: no authorization decision is made here -- omnibioai-auth's
# own require_org_permission_or_platform_admin(MANAGE_TEAMS) (mutations)
# and get_org_membership_or_platform_admin (listing) decide every
# request, both pre-existing and unmodified by this PR. A separate file
# from the others -- same "one concern per proxy file" choice each of
# them already made, now applied a fourth time.
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

    # DELETE /orgs/{org_id}/teams/{team_id} succeeds with 204 and an empty
    # body -- same case routes_role_proxy.py's _proxy already handles for
    # its own DELETE routes; r.json() on an empty body raises, so the
    # empty body is preserved faithfully instead of inventing a fake JSON
    # payload for it.
    if not r.content:
        return Response(status_code=r.status_code)

    try:
        payload = r.json()
    except ValueError:
        payload = {"error": "auth-service returned a non-JSON response"}
    return JSONResponse(payload, status_code=r.status_code)


@router.get("/orgs/{org_id}/teams")
async def list_teams_proxy(org_id: int, request: Request) -> Response:
    return await _proxy("GET", f"/orgs/{org_id}/teams", request)


@router.post("/orgs/{org_id}/teams")
async def create_team_proxy(org_id: int, request: Request) -> Response:
    return await _proxy("POST", f"/orgs/{org_id}/teams", request)


@router.put("/orgs/{org_id}/teams/{team_id}/members")
async def update_team_members_proxy(org_id: int, team_id: int, request: Request) -> Response:
    return await _proxy("PUT", f"/orgs/{org_id}/teams/{team_id}/members", request)


@router.delete("/orgs/{org_id}/teams/{team_id}")
async def delete_team_proxy(org_id: int, team_id: int, request: Request) -> Response:
    return await _proxy("DELETE", f"/orgs/{org_id}/teams/{team_id}", request)
