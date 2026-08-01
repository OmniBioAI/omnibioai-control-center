from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

# Phase 3 PR2 (Organizations page). Same reasoning as routes_auth_proxy.py:
# control.omnibioai.org's Cloudflare Tunnel ingress bypasses nginx-router
# entirely, so there is no `location ^~ /orgs/ { proxy_pass http://auth; }`
# (or /platform/) in front of this domain either -- a bare fetch('/orgs')
# from the Organizations page would otherwise 404 against control-center
# itself, which has no such routes of its own.
#
# Deliberately a separate file from routes_auth_proxy.py rather than an
# extension of it: that file's own scope/docstring is specifically
# `/auth/*`, and its two routes never needed to forward an Authorization
# header (login/validate calls happen before a session exists). These
# routes must forward it, since omnibioai-auth's own require_permission/
# require_org_permission_or_platform_admin (Phase 3 PR0.4) is what
# actually decides whether a request succeeds -- no authorization
# decision is made here, only relaying. Keeping the two proxy concerns in
# separate, individually-small files was judged clearer than growing one
# file to cover both, at the cost of ~15 duplicated boilerplate lines.
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


# ---------------- Org-scoped (existing /orgs surface, unmodified upstream) ----------------


@router.get("/orgs")
async def list_my_orgs_proxy(request: Request) -> JSONResponse:
    return await _proxy("GET", "/orgs", request)


@router.post("/orgs")
async def create_org_proxy(request: Request) -> JSONResponse:
    return await _proxy("POST", "/orgs", request)


@router.get("/orgs/{org_id}")
async def get_org_proxy(org_id: int, request: Request) -> JSONResponse:
    return await _proxy("GET", f"/orgs/{org_id}", request)


@router.patch("/orgs/{org_id}")
async def update_org_proxy(org_id: int, request: Request) -> JSONResponse:
    return await _proxy("PATCH", f"/orgs/{org_id}", request)


# Phase 3 PR3B: added for the new Members & Roles section on
# OrganizationDetailPage.tsx -- GET /orgs/{org_id}/members has existed in
# omnibioai-auth since Phase 1 PR2 (routes_orgs.py's list_members), but
# nothing on this side ever proxied it until this PR needed the member
# list to render alongside each member's role editor.
@router.get("/orgs/{org_id}/members")
async def list_org_members_proxy(org_id: int, request: Request) -> JSONResponse:
    return await _proxy("GET", f"/orgs/{org_id}/members", request)


# ---------------- Platform-admin discovery (Phase 3 PR1) ----------------


@router.get("/platform/orgs")
async def list_platform_orgs_proxy(request: Request) -> JSONResponse:
    return await _proxy("GET", "/platform/orgs", request)


@router.get("/platform/orgs/{org_id}")
async def get_platform_org_proxy(org_id: int, request: Request) -> JSONResponse:
    return await _proxy("GET", f"/platform/orgs/{org_id}", request)
