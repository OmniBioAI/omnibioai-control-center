from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

# control.omnibioai.org's Cloudflare Tunnel ingress rule routes directly to
# control-center's own :7070 (see /etc/cloudflared/config.yml's "Admin
# only" group), bypassing nginx-router entirely -- unlike every other
# webstudio.omnibioai.org path, there is no nginx `location ^~ /auth/
# { proxy_pass http://auth; }` in front of this domain to reach
# auth-service. The Admin tab's fetch('/auth/login')/fetch('/auth/validate')
# calls (bare relative paths, deliberately not routed through admApi()
# since /auth/* isn't nested under /_svc/control) otherwise 404 against
# control-center itself, which has no such routes of its own.
#
# These two routes mirror nginx-router.conf's own /auth/ proxy, scoped to
# just what the Admin tab needs, using the same internal hostname
# (IAM_URL) api-gateway and model-registry already use to reach
# auth-service.
router = APIRouter()

IAM_URL = os.environ.get("IAM_URL", "http://auth-service:8001")


async def _proxy_to_auth(path: str, request: Request) -> JSONResponse:
    body = await request.body()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{IAM_URL}{path}",
                content=body,
                headers={"Content-Type": "application/json"},
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


@router.post("/auth/login")
async def auth_login_proxy(request: Request) -> JSONResponse:
    return await _proxy_to_auth("/auth/login", request)


@router.post("/auth/validate")
async def auth_validate_proxy(request: Request) -> JSONResponse:
    return await _proxy_to_auth("/auth/validate", request)
