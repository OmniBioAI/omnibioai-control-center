"""Transparent relay for auth-service manual-license administration."""
from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

router = APIRouter()
IAM_URL = os.environ.get("IAM_URL", "http://auth-service:8001")


async def _proxy(method: str, path: str, request: Request) -> Response:
    headers = {"Content-Type": "application/json"}
    if auth := request.headers.get("authorization"):
        headers["Authorization"] = auth
    if idem := request.headers.get("idempotency-key"):
        headers["Idempotency-Key"] = idem
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            upstream = await client.request(
                method,
                f"{IAM_URL}{path}",
                params=request.query_params,
                content=await request.body() if method in {"POST", "PUT", "PATCH"} else None,
                headers=headers,
            )
    except httpx.RequestError as error:
        return JSONResponse(
            {"error": f"auth-service unreachable: {type(error).__name__}"}, status_code=503,
        )
    if not upstream.content:
        return Response(status_code=upstream.status_code)
    try:
        payload = upstream.json()
    except ValueError:
        payload = {"error": "auth-service returned a non-JSON response"}
    return JSONResponse(payload, status_code=upstream.status_code)


@router.get("/platform/licenses/policy")
async def policy(request: Request) -> Response:
    return await _proxy("GET", "/platform/licenses/policy", request)


@router.get("/platform/licenses")
async def list_licenses(request: Request) -> Response:
    return await _proxy("GET", "/platform/licenses", request)


@router.post("/platform/licenses")
async def issue_license(request: Request) -> Response:
    return await _proxy("POST", "/platform/licenses", request)


@router.get("/platform/licenses/{license_id}")
async def get_license(license_id: int, request: Request) -> Response:
    return await _proxy("GET", f"/platform/licenses/{license_id}", request)


@router.post("/platform/licenses/{license_id}/revoke")
async def revoke_license(license_id: int, request: Request) -> Response:
    return await _proxy("POST", f"/platform/licenses/{license_id}/revoke", request)


@router.post("/platform/licenses/{license_id}/renew")
async def renew_license(license_id: int, request: Request) -> Response:
    return await _proxy("POST", f"/platform/licenses/{license_id}/renew", request)


@router.get("/platform/licenses/{license_id}/history")
async def history(license_id: int, request: Request) -> Response:
    return await _proxy("GET", f"/platform/licenses/{license_id}/history", request)
