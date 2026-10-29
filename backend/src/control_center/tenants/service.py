from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Any

import httpx

IAM_URL = os.environ.get("IAM_URL", "http://auth-service:8001")
BILLING_URL = os.environ.get("BILLING_URL", "http://billing-service:8005")
WORKBENCH_URL = os.environ.get("WORKBENCH_URL", "http://workbench:8000")
POOL_CAPACITY_BYTES = int(os.environ.get("TENANT_STORAGE_POOL_CAPACITY_BYTES", "0"))
PAGE_LIMIT = 100
PLAN_BYTES = {"free": 1_000_000_000, "plus": 20_000_000_000, "pro": 100_000_000_000}
MEMBERSHIP_STATUSES = {"active", "trialing", "past_due", "canceled", "none"}


class UpstreamError(RuntimeError):
    def __init__(self, service: str, status_code: int, detail: str):
        super().__init__(detail)
        self.service = service
        self.status_code = status_code
        self.detail = detail


def _headers(authorization: str | None) -> dict[str, str]:
    return {"Authorization": authorization, "Content-Type": "application/json"} if authorization else {"Content-Type": "application/json"}


async def _json(client: httpx.AsyncClient, method: str, url: str, service: str, headers: dict[str, str], **kwargs) -> dict:
    try:
        response = await client.request(method, url, headers=headers, timeout=10, **kwargs)
    except httpx.RequestError as exc:
        raise UpstreamError(service, 503, f"{service} unavailable") from exc
    if response.status_code >= 400:
        try:
            payload = response.json()
            detail = payload.get("detail") or payload.get("error") or f"{service} returned {response.status_code}"
        except ValueError:
            detail = f"{service} returned {response.status_code}"
        raise UpstreamError(service, response.status_code, str(detail))
    try:
        return response.json()
    except ValueError as exc:
        raise UpstreamError(service, 502, f"{service} returned invalid JSON") from exc


async def _all_user_ids(client: httpx.AsyncClient, headers: dict[str, str]) -> list[str]:
    ids: list[str] = []
    page = 1
    while True:
        payload = await _json(client, "GET", f"{IAM_URL}/platform/users", "auth-service", headers, params={"page": page, "page_size": PAGE_LIMIT, "sort_by": "created_at", "sort_order": "asc"})
        ids.extend(str(item["id"]) for item in payload.get("items", []))
        if page >= int(payload.get("total_pages") or 0):
            break
        page += 1
    return ids


async def _sources(client: httpx.AsyncClient, headers: dict[str, str], ids: list[str]) -> tuple[dict, dict, dict]:
    identities: dict[str, dict] = {}
    billings: dict[str, dict] = {}
    ledgers: dict[str, dict] = {}
    for start in range(0, len(ids), 1000):
        chunk = ids[start:start + 1000]
        identity = await _json(client, "POST", f"{IAM_URL}/platform/users/batch", "auth-service", headers, json={"user_ids": [int(value) for value in chunk]})
        billing = await _json(client, "POST", f"{BILLING_URL}/admin/tenants/resolve", "billing-service", headers, json={"user_ids": chunk})
        ledger = await _json(client, "POST", f"{WORKBENCH_URL}/api/storage/admin/tenants/resolve", "workbench", headers, json={"user_ids": chunk})
        identities.update({str(item["user_id"]): item for item in identity.get("items", [])})
        billings.update({str(item["user_id"]): item for item in billing.get("items", [])})
        ledgers.update({str(item["user_id"]): item for item in ledger.get("items", [])})
    return identities, billings, ledgers


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


def tenant_row(identity: dict, billing: dict, ledger: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    valid_until = _parse(billing.get("valid_until"))
    days_remaining = math.ceil((valid_until - now).total_seconds() / 86400) if valid_until else None
    raw_status = str(billing.get("membership_status", "none"))
    status = raw_status if raw_status in MEMBERSHIP_STATUSES else ("canceled" if raw_status in {"incomplete_expired", "unpaid"} else "past_due")
    plan_id = billing.get("plan_id") if billing.get("plan_id") in PLAN_BYTES else "free"
    effective_plan = billing.get("effective_plan_id") if billing.get("effective_plan_id") in PLAN_BYTES else "free"
    if status in {"canceled", "none"} or (days_remaining is not None and days_remaining < 0):
        effective_plan = "free"
    override = billing.get("override")
    allocated = int(override["allocated_bytes"]) if override else PLAN_BYTES[effective_plan]
    used = int(ledger.get("used_bytes") or 0)
    reserved = int(ledger.get("reserved_bytes") or 0)
    pct = round((used / allocated * 100) if allocated else 0, 2)
    storage_status = "over_allocation" if used > allocated else ("near" if pct >= 80 else "ok")
    history = billing.get("plan_history") or []
    last = history[0] if history else None
    return {
        "tenant_id": str(identity["user_id"]), "username": identity.get("username") or identity.get("email", "").split("@", 1)[0], "email": identity.get("email", ""),
        "plan_id": plan_id, "membership_status": status, "effective_plan_id": effective_plan,
        "valid_from": billing.get("valid_from"), "valid_until": billing.get("valid_until"), "auto_renew": bool(billing.get("auto_renew")), "days_remaining": days_remaining,
        "allocated_bytes": allocated, "allocation_source": "override" if override else "plan", "used_bytes": used, "reserved_bytes": reserved, "pct": pct, "storage_status": storage_status,
        "last_plan_change": ({"from_plan": last["from_plan"], "to_plan": last["to_plan"], "at": last["at"]} if last else None), "last_activity_at": identity.get("last_activity_at"),
    }


def filter_sort(rows: list[dict], *, plan: str | None = None, status: str | None = None, validity: str | None = None, storage_status: str | None = None, q: str | None = None, sort: str = "username") -> list[dict]:
    needle = (q or "").strip().lower()
    result = [row for row in rows if
        (not plan or row["effective_plan_id"] == plan) and
        (not status or row["membership_status"] == status) and
        (not storage_status or row["storage_status"] == storage_status) and
        (not needle or any(needle in str(row[field]).lower() for field in ("tenant_id", "username", "email"))) and
        (not validity or (validity == "expired" and row["days_remaining"] is not None and row["days_remaining"] < 0) or (validity == "expiring_7d" and row["days_remaining"] is not None and 0 <= row["days_remaining"] <= 7) or (validity == "expiring_30d" and row["days_remaining"] is not None and 0 <= row["days_remaining"] <= 30))
    ]
    descending = sort.startswith("-")
    key = sort[1:] if descending else sort
    if rows and key not in rows[0]:
        key = "username"
    def sortable(row: dict):
        value = row.get(key)
        if isinstance(value, dict):
            value = value.get("at")
        if isinstance(value, (int, float)):
            return (value is None, 0, value)
        return (value is None, 1, str(value or "").lower())
    return sorted(result, key=sortable, reverse=descending)


async def all_tenants(authorization: str | None) -> tuple[list[dict], dict, dict]:
    headers = _headers(authorization)
    async with httpx.AsyncClient() as client:
        ids = await _all_user_ids(client, headers)
        if not ids:
            return [], {}, {}
        identities, billings, ledgers = await _sources(client, headers, ids)
    rows = [tenant_row(identities[user_id], billings.get(user_id, {}), ledgers.get(user_id, {})) for user_id in ids if user_id in identities]
    return rows, billings, ledgers


async def tenant_detail(tenant_id: str, authorization: str | None) -> dict | None:
    headers = _headers(authorization)
    async with httpx.AsyncClient() as client:
        identities, billings, ledgers = await _sources(client, headers, [tenant_id])
    if tenant_id not in identities:
        return None
    row = tenant_row(identities[tenant_id], billings.get(tenant_id, {}), ledgers.get(tenant_id, {}))
    return {**row, "plan_history": billings.get(tenant_id, {}).get("plan_history", []), "override": billings.get(tenant_id, {}).get("override"), "top_allocations": ledgers.get(tenant_id, {}).get("top_allocations", []), "workflow_output_bytes": ledgers.get(tenant_id, {}).get("workflow_output_bytes", 0), "usage_trend_30d": ledgers.get(tenant_id, {}).get("usage_trend_30d", [])}


def summary(rows: list[dict]) -> dict:
    return {
        "tenants_total": len(rows),
        "per_plan": {plan: sum(row["effective_plan_id"] == plan for row in rows) for plan in PLAN_BYTES},
        "allocated_sum_bytes": sum(row["allocated_bytes"] for row in rows), "used_sum_bytes": sum(row["used_bytes"] for row in rows), "pool_capacity_bytes": POOL_CAPACITY_BYTES,
        "expiring_7d": sum(row["days_remaining"] is not None and 0 <= row["days_remaining"] <= 7 for row in rows), "past_due": sum(row["membership_status"] == "past_due" for row in rows), "over_allocation": sum(row["storage_status"] == "over_allocation" for row in rows),
    }


async def mutate(method: str, tenant_id: str, suffix: str, body: dict, authorization: str | None, target: str) -> dict | None:
    base, service = (BILLING_URL, "billing-service") if target == "billing" else (WORKBENCH_URL + "/api/storage", "workbench")
    headers = _headers(authorization)
    async with httpx.AsyncClient() as client:
        return await _json(client, method, f"{base}/admin/tenants/{tenant_id}/{suffix}", service, headers, json=body)
