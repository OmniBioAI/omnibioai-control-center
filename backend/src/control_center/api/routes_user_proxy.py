from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

# Phase 3 PR3A (Users page). Same reasoning as routes_org_proxy.py (Phase
# 3 PR2) and routes_auth_proxy.py before it: control.omnibioai.org's
# Cloudflare Tunnel ingress bypasses nginx-router entirely, so there is no
# proxy rule for /platform/users in front of this domain either. No
# authorization decision is made here -- omnibioai-auth's own
# require_permission(MANAGE_ALL_ORGS) (Phase 3 PR0.4/PR1/PR3A) is what
# actually decides every request; this file only relays bytes and
# forwards the Authorization header.
#
# A separate file from routes_org_proxy.py, not an extension of it --
# same "one concern per proxy file" choice that file's own docstring
# already explains, now applied a second time.
router = APIRouter()

IAM_URL = os.environ.get("IAM_URL", "http://auth-service:8001")


async def _proxy(method: str, path: str, request: Request) -> JSONResponse:
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

    try:
        payload = r.json()
    except ValueError:
        payload = {"error": "auth-service returned a non-JSON response"}
    return JSONResponse(payload, status_code=r.status_code)


@router.get("/platform/users")
async def list_platform_users_proxy(request: Request) -> JSONResponse:
    return await _proxy("GET", "/platform/users", request)


@router.get("/platform/users/{user_id}")
async def get_platform_user_proxy(user_id: int, request: Request) -> JSONResponse:
    return await _proxy("GET", f"/platform/users/{user_id}", request)


@router.patch("/platform/users/{user_id}")
async def update_platform_user_proxy(user_id: int, request: Request) -> JSONResponse:
    return await _proxy("PATCH", f"/platform/users/{user_id}", request)
