from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

router = APIRouter()

SECURITY_AUDIT_URL = os.environ.get("SECURITY_AUDIT_URL", "http://security-audit:8004")
_SAFE_QUERY_KEYS = frozenset({
    "page", "page_size", "user_id", "service", "event_type", "decision",
    "from_timestamp", "to_timestamp", "integrity_status", "organization_id",
})


async def _proxy_safe_audit(request: Request) -> Response:
    # The upstream owns authentication, tenant scope, filtering semantics, and
    # safe metadata projection. Control Center only forwards the verified
    # bearer token and the contract's bounded query parameters.
    params = [(key, value) for key, value in request.query_params.multi_items()
              if key in _SAFE_QUERY_KEYS]
    headers = {}
    authorization = request.headers.get("authorization")
    if authorization:
        headers["Authorization"] = authorization
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            upstream = await client.request(
                "GET",
                f"{SECURITY_AUDIT_URL}/audit/events/safe",
                params=params,
                headers=headers,
            )
    except httpx.RequestError:
        return JSONResponse({"error": "AUDIT_SOURCE_UNAVAILABLE"}, status_code=503)

    if upstream.status_code in (401, 403, 422):
        errors = {401: "UNAUTHENTICATED", 403: "FORBIDDEN", 422: "VALIDATION_ERROR"}
        return JSONResponse({"error": errors[upstream.status_code]}, status_code=upstream.status_code)
    if upstream.status_code == 503:
        return JSONResponse({"error": "AUDIT_SOURCE_UNAVAILABLE"}, status_code=503)
    if not 200 <= upstream.status_code < 300:
        return JSONResponse({"error": "AUDIT_SOURCE_UNAVAILABLE"}, status_code=503)
    try:
        return JSONResponse(upstream.json(), status_code=200)
    except ValueError:
        return JSONResponse({"error": "AUDIT_SOURCE_UNAVAILABLE"}, status_code=503)


@router.get("/audit/events/safe")
async def list_security_audit_events(request: Request) -> Response:
    return await _proxy_safe_audit(request)
