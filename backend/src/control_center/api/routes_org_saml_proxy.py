from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

# PR9 (SAML Admin UI). Same reasoning as routes_org_sso_proxy.py
# (PR11.3), routes_org_mfa_proxy.py (PR11.5.6), and every other *_proxy.py
# in this file: no authorization decision is made here -- omnibioai-
# auth's own require_org_permission_or_platform_admin(MANAGE_SSO) (the 4
# CRUD routes, PR8/auth#49) decides every request, pre-existing and
# unmodified by this PR. This file is a pure relay: it never inspects,
# caches, or logs the request/response bodies it forwards. Unlike
# routes_org_sso_proxy.py there is no client_secret to worry about here
# -- x509_certificate is a public certificate (see omnibioai-auth's own
# OrganizationSAMLConfig docstring) -- but the same "never add local
# logic" discipline still applies.
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

    # DELETE /orgs/{org_id}/saml succeeds with 204 and an empty body --
    # same case routes_org_sso_proxy.py's/routes_team_proxy.py's own
    # _proxy already handle for their own DELETE routes; r.json() on an
    # empty body raises, so the empty body is preserved faithfully
    # instead of inventing a fake JSON payload for it.
    if not r.content:
        return Response(status_code=r.status_code)

    try:
        payload = r.json()
    except ValueError:
        payload = {"error": "auth-service returned a non-JSON response"}
    return JSONResponse(payload, status_code=r.status_code)


# ---------------- Org-scoped SAML configuration ----------------


@router.get("/orgs/{org_id}/saml")
async def get_org_saml_proxy(org_id: int, request: Request) -> Response:
    return await _proxy("GET", f"/orgs/{org_id}/saml", request)


@router.post("/orgs/{org_id}/saml")
async def create_org_saml_proxy(org_id: int, request: Request) -> Response:
    return await _proxy("POST", f"/orgs/{org_id}/saml", request)


@router.patch("/orgs/{org_id}/saml")
async def update_org_saml_proxy(org_id: int, request: Request) -> Response:
    return await _proxy("PATCH", f"/orgs/{org_id}/saml", request)


@router.delete("/orgs/{org_id}/saml")
async def delete_org_saml_proxy(org_id: int, request: Request) -> Response:
    return await _proxy("DELETE", f"/orgs/{org_id}/saml", request)


# ---------------- SP metadata (public/unauthenticated upstream) --------
#
# GET /auth/saml/{org_slug}/metadata (omnibioai-auth's routes_saml.py,
# PR3) is deliberately unauthenticated -- an external IdP administrator,
# not a logged-in control-center user, is its intended eventual
# consumer. It's still proxied through here rather than the browser
# hitting omnibioai-auth directly, for the same reason every other
# surface in this file is: the control-center frontend only ever calls
# its own origin at a relative path (see saml.ts's own module docstring)
# -- there is no browser-reachable, CORS-enabled path to omnibioai-auth
# from this app at all, IAM_URL is a server-to-server-only address.
#
# Deliberately NOT built on the shared _proxy() helper above: that
# helper always parses the upstream body as JSON (or treats empty-body
# as a bare 204), which would corrupt this endpoint's raw XML
# (application/samlmetadata+xml) response. This handler instead forwards
# the upstream status/content-type/bytes through unmodified, the same
# `Response(content=..., media_type=...)` shape
# control_center.compliance.router already uses for its own non-JSON
# (PDF/CSV) responses.
#
# org_slug is a path parameter here, not client-supplied JSON/state --
# SAMLSettingsPage.tsx resolves it from the already-authenticated
# fetchMyOrg/fetchPlatformOrgDetail response (trusted server data), never
# from arbitrary UI state, exactly as PR9's own task spec requires.
@router.get("/auth/saml/{org_slug}/metadata")
async def get_saml_metadata_proxy(org_slug: str, request: Request) -> Response:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{IAM_URL}/auth/saml/{org_slug}/metadata")
    except httpx.RequestError as e:
        return JSONResponse(
            {"error": f"auth-service unreachable: {type(e).__name__}: {e}"}, status_code=503,
        )

    return Response(
        content=r.content,
        media_type=r.headers.get("content-type", "application/samlmetadata+xml"),
        status_code=r.status_code,
    )
