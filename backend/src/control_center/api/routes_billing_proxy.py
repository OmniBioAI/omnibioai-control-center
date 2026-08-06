from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

# PR14.5C (Billing APIs + Control Center Invoice UI). Same reasoning as
# routes_org_proxy.py (PR2), routes_org_sso_proxy.py (PR11.3), and every
# other *_proxy.py in this package: no authorization decision is made
# here -- omnibioai-billing's own app.core.iam.get_authorized_
# organization_id/get_authorized_invoice (independent JWT verification,
# not a trust-the-gateway-header shortcut) decide every request. This
# file only relays the Authorization header verbatim and preserves the
# upstream status code.
#
# All five routes are read-only (GET) -- PR14.5C is billing visibility
# and invoice management only, no payment/write endpoints exist on the
# billing service yet, so unlike routes_org_sso_proxy.py's _proxy this
# one never needs to forward a request body or handle a 204 empty
# response.
router = APIRouter()

BILLING_URL = os.environ.get("BILLING_URL", "http://billing-service:8005")


async def _proxy(path: str, request: Request) -> JSONResponse:
    headers = {"Content-Type": "application/json"}
    auth_header = request.headers.get("authorization")
    if auth_header:
        headers["Authorization"] = auth_header

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{BILLING_URL}{path}",
                params=request.query_params,
                headers=headers,
            )
    except httpx.RequestError as e:
        return JSONResponse(
            {"error": f"billing-service unreachable: {type(e).__name__}: {e}"}, status_code=503,
        )

    try:
        payload = r.json()
    except ValueError:
        payload = {"error": "billing-service returned a non-JSON response"}
    return JSONResponse(payload, status_code=r.status_code)


# ---------------- Organization-scoped billing reporting ----------------


@router.get("/billing/organizations/{organization_id}/summary")
async def get_organization_billing_summary_proxy(organization_id: int, request: Request) -> JSONResponse:
    return await _proxy(f"/billing/organizations/{organization_id}/summary", request)


@router.get("/billing/organizations/{organization_id}/invoices")
async def list_organization_invoices_proxy(organization_id: int, request: Request) -> JSONResponse:
    return await _proxy(f"/billing/organizations/{organization_id}/invoices", request)


@router.get("/billing/organizations/{organization_id}/cost-breakdown")
async def get_organization_cost_breakdown_proxy(organization_id: int, request: Request) -> JSONResponse:
    return await _proxy(f"/billing/organizations/{organization_id}/cost-breakdown", request)


# ---------------- Invoice-scoped ----------------


@router.get("/billing/invoices/{invoice_id}")
async def get_invoice_detail_proxy(invoice_id: int, request: Request) -> JSONResponse:
    return await _proxy(f"/billing/invoices/{invoice_id}", request)


@router.get("/billing/invoices/{invoice_id}/line-items")
async def get_invoice_line_items_proxy(invoice_id: int, request: Request) -> JSONResponse:
    return await _proxy(f"/billing/invoices/{invoice_id}/line-items", request)
