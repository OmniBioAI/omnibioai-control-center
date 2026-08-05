from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

# PR11.4 (Enterprise Service Accounts & API Keys Management UI). Same
# reasoning as routes_org_proxy.py (PR2), routes_role_proxy.py (PR3B),
# and routes_team_proxy.py (PR3C) before it: no authorization decision
# is made here -- omnibioai-auth's own require_org_permission_or_
# platform_admin(manage_api_keys / manage_oauth_clients) and
# require_permission(manage_all_orgs) (the read-only permission
# registry passthrough) decide every request, all pre-existing and
# unmodified by this PR. A pure relay: never inspects, caches, or logs
# the request/response bodies it forwards -- matters here specifically
# because POST responses carry a plaintext api_key/client_secret on the
# way back. See this PR's own docs/admin-console-pr11-service-accounts.md
# for the full secret-handling note.
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

    # DELETE .../api-keys/{id} and .../oauth-clients/{id} both succeed
    # with 204 and an empty body -- same case routes_team_proxy.py's/
    # routes_role_proxy.py's _proxy already handle for their own DELETE
    # routes; r.json() on an empty body raises, so the empty body is
    # preserved faithfully instead of inventing a fake JSON payload.
    if not r.content:
        return Response(status_code=r.status_code)

    try:
        payload = r.json()
    except ValueError:
        payload = {"error": "auth-service returned a non-JSON response"}
    return JSONResponse(payload, status_code=r.status_code)


# ---------------- API Keys ----------------


@router.get("/orgs/{org_id}/api-keys")
async def list_api_keys_proxy(org_id: int, request: Request) -> Response:
    return await _proxy("GET", f"/orgs/{org_id}/api-keys", request)


@router.post("/orgs/{org_id}/api-keys")
async def create_api_key_proxy(org_id: int, request: Request) -> Response:
    return await _proxy("POST", f"/orgs/{org_id}/api-keys", request)


@router.delete("/orgs/{org_id}/api-keys/{key_id}")
async def revoke_api_key_proxy(org_id: int, key_id: int, request: Request) -> Response:
    return await _proxy("DELETE", f"/orgs/{org_id}/api-keys/{key_id}", request)


# ---------------- OAuth Clients / Service Accounts ----------------


@router.get("/orgs/{org_id}/oauth-clients")
async def list_oauth_clients_proxy(org_id: int, request: Request) -> Response:
    return await _proxy("GET", f"/orgs/{org_id}/oauth-clients", request)


@router.post("/orgs/{org_id}/oauth-clients")
async def create_oauth_client_proxy(org_id: int, request: Request) -> Response:
    return await _proxy("POST", f"/orgs/{org_id}/oauth-clients", request)


@router.delete("/orgs/{org_id}/oauth-clients/{client_id}")
async def revoke_oauth_client_proxy(org_id: int, client_id: int, request: Request) -> Response:
    return await _proxy("DELETE", f"/orgs/{org_id}/oauth-clients/{client_id}", request)


# ---------------- Permission registry (read-only, platform-admin only) ----

# Scope picker support only (see docs/admin-console-pr11-service-accounts-
# discovery.md §6) -- omnibioai-auth's own require_permission
# (manage_all_orgs) on the upstream route means a non-platform-admin
# caller gets a 403 here exactly as they would calling omnibioai-auth
# directly; this proxy adds no additional restriction and no fallback.
@router.get("/platform/permissions")
async def list_permissions_proxy(request: Request) -> Response:
    return await _proxy("GET", "/platform/permissions", request)
