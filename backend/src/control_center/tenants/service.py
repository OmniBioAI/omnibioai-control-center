from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field

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
    return [str(item["id"]) for item in await _directory(client, headers)]


async def _directory(client, headers, **filters) -> list[dict]:
    items = []
    page = 1
    while True:
        payload = await _json(client, "GET", f"{IAM_URL}/platform/users", "auth-service", headers, params={"page": page, "page_size": PAGE_LIMIT, "sort_by": "created_at", "sort_order": "asc", **filters})
        items.extend(payload.get("items", []))
        if page >= int(payload.get("total_pages") or 0):
            break
        page += 1
    return items


async def _sources(client: httpx.AsyncClient, headers: dict[str, str], ids: list[str]) -> tuple[dict, dict, dict]:
    identities: dict[str, dict] = {}
    billings: dict[str, dict] = {}
    ledgers: dict[str, dict] = {}
    for start in range(0, len(ids), 1000):
        chunk = ids[start:start + 1000]
        identity, billing, ledger = await asyncio.gather(
            _json(client, "POST", f"{IAM_URL}/platform/users/batch", "auth-service", headers, json={"user_ids": [int(value) for value in chunk]}),
            _json(client, "POST", f"{BILLING_URL}/admin/tenants/resolve", "billing-service", headers, json={"user_ids": chunk}),
            _json(client, "POST", f"{WORKBENCH_URL}/api/storage/admin/tenants/resolve", "workbench", headers, json={"user_ids": chunk}),
        )
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
    valid_until = _parse(billing.get("promo_expires_at") if billing.get("plan_source") == "promo" else billing.get("valid_until"))
    days_remaining = math.ceil((valid_until - now).total_seconds() / 86400) if valid_until else None
    raw_status = str(billing.get("membership_status", "none"))
    status = raw_status if raw_status in MEMBERSHIP_STATUSES else ("canceled" if raw_status in {"incomplete_expired", "unpaid"} else "past_due")
    plan_id = billing.get("plan_id") if billing.get("plan_id") in PLAN_BYTES else "free"
    effective_plan = billing.get("effective_plan_id") if billing.get("effective_plan_id") in PLAN_BYTES else "free"
    plan_source = billing.get("plan_source") if billing.get("plan_source") in {"stripe", "promo", "free"} else ("stripe" if effective_plan != "free" else "free")
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
        "plan_source": plan_source, "promo_expires_at": billing.get("promo_expires_at"),
        "valid_from": billing.get("valid_from"), "valid_until": billing.get("valid_until"), "auto_renew": bool(billing.get("auto_renew")), "days_remaining": days_remaining,
        "allocated_bytes": allocated, "allocation_source": "override" if override else "plan", "used_bytes": used, "reserved_bytes": reserved, "pct": pct, "storage_status": storage_status,
        "last_plan_change": ({"from_plan": last["from_plan"], "to_plan": last["to_plan"], "at": last["at"]} if last else None), "last_activity_at": identity.get("last_activity_at"),
    }


def filter_sort(rows: list[dict], *, plan: str | None = None, plan_source: str | None = None, status: str | None = None, validity: str | None = None, storage_status: str | None = None, q: str | None = None, sort: str = "username") -> list[dict]:
    needle = (q or "").strip().lower()
    result = [row for row in rows if
        (not plan or row["effective_plan_id"] == plan) and
        (not plan_source or row["plan_source"] == plan_source) and
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
        value = row.get("promo_expires_at") if key == "valid_until" and row.get("plan_source") == "promo" else row.get(key)
        if isinstance(value, dict):
            value = value.get("at")
        if isinstance(value, (int, float)):
            return (value is None, 0, value)
        return (value is None, 1, str(value or "").lower())
    # Stable tie ordering makes pagination deterministic.
    result.sort(key=lambda row: int(row["tenant_id"]))
    return sorted(result, key=sortable, reverse=descending)


async def all_tenants(authorization: str | None) -> tuple[list[dict], dict, dict]:
    headers = _headers(authorization)
    async with httpx.AsyncClient() as client:
        directory = await _directory(client, headers)
        ids = [str(item["id"]) for item in directory]
        if not ids:
            return [], {}, {}
        identities, billings, ledgers = await _sources(client, headers, ids)
    users = {str(item["id"]): item for item in directory}
    rows = [{**users[user_id], **tenant_row(identities[user_id], billings.get(user_id, {}), ledgers.get(user_id, {}))} for user_id in ids if user_id in identities]
    return rows, billings, ledgers


async def tenant_detail(tenant_id: str, authorization: str | None) -> dict | None:
    headers = _headers(authorization)
    async with httpx.AsyncClient() as client:
        identity = await _json(client, "POST", f"{IAM_URL}/platform/users/batch", "auth-service", headers, json={"user_ids": [int(tenant_id)]})
        identities = {str(item["user_id"]): item for item in identity.get("items", [])}
        if tenant_id not in identities:
            return None
        billing = await _json(client, "GET", f"{BILLING_URL}/admin/tenants/{tenant_id}", "billing-service", headers)
        ledger = await _json(client, "GET", f"{WORKBENCH_URL}/api/storage/admin/tenants/{tenant_id}", "workbench", headers)
        # Preserve audit identifiers; add display labels using Auth's batch lookup.
        history = billing.get("plan_history", [])
        actor_ids = sorted({int(h["actor"][5:]) for h in history
                            if isinstance(h.get("actor"), str) and h["actor"].startswith("user:")
                            and h["actor"][5:].isascii() and h["actor"][5:].isdigit()})
        actors = {}
        for start in range(0, len(actor_ids), 1000):
            try:
                result = await _json(client, "POST", f"{IAM_URL}/platform/users/batch", "auth-service", headers,
                                     json={"user_ids": actor_ids[start:start + 1000]})
            except UpstreamError:
                continue  # Identity lookup failure must not hide the audit history.
            actors.update({f"user:{item['user_id']}": item.get("email") or item.get("username")
                           for item in result.get("items", [])})
        billing["plan_history"] = [{**h, "actor_display": actors.get(h.get("actor"))} for h in history]
    row = tenant_row(identities[tenant_id], billing, ledger)
    for entry in _indexes.values():
        if entry.rows is not None:
            entry.rows = [{**item, **row} if item["tenant_id"] == tenant_id else item for item in entry.rows]
            entry.aggregate = summary(entry.rows)
    return {**row, "plan_history": billing.get("plan_history", []), "override": billing.get("override"), "active_grant": billing.get("active_grant"), "grant_history": billing.get("grant_history", []), "top_allocations": ledger.get("top_allocations", []), "workflow_output_bytes": ledger.get("workflow_output_bytes", 0), "usage_trend_30d": ledger.get("usage_trend_30d", [])}


def summary(rows: list[dict], now: datetime | None = None) -> dict:
    moment = now or datetime.now(timezone.utc)
    return {
        "tenants_total": len(rows),
        "per_plan": {plan: sum(row["effective_plan_id"] == plan for row in rows) for plan in PLAN_BYTES},
        "allocated_sum_bytes": sum(row["allocated_bytes"] for row in rows), "used_sum_bytes": sum(row["used_bytes"] for row in rows), "pool_capacity_bytes": POOL_CAPACITY_BYTES,
        "expiring_7d": sum(row["days_remaining"] is not None and 0 <= row["days_remaining"] <= 7 for row in rows), "past_due": sum(row["membership_status"] == "past_due" for row in rows), "over_allocation": sum(row["storage_status"] == "over_allocation" for row in rows),
        "promos_active": sum(bool(row["promo_expires_at"]) for row in rows),
        "promos_expiring_7d": sum(bool(row["promo_expires_at"]) and 0 <= math.ceil((_parse(row["promo_expires_at"]) - moment).total_seconds() / 86400) <= 7 for row in rows),
    }


async def mutate(method: str, tenant_id: str, suffix: str, body: dict, authorization: str | None, target: str) -> dict | None:
    base, service = (BILLING_URL, "billing-service") if target == "billing" else (WORKBENCH_URL + "/api/storage", "workbench")
    headers = _headers(authorization)
    async with httpx.AsyncClient() as client:
        result = await _json(client, method, f"{base}/admin/tenants/{tenant_id}/{suffix}", service, headers, json=body)
    invalidate_index()
    return result


# A bounded per-credential cache: permission checks still run on every route,
# and one administrator's upstream-authorized data is never reused for another.
# Only the background refresh enumerates the directory. List requests resolve
# at most their selected page, even while an expired index is refreshing.
INDEX_TTL = 60.0
MAX_INDEXES = 8


@dataclass
class TenantIndex:
    rows: list[dict] | None = None
    aggregate: dict = field(default_factory=dict)
    updated_at: float = 0.0
    retry_after: float = 0.0
    task: asyncio.Task | None = None
    error: UpstreamError | None = None


_indexes: dict[str, TenantIndex] = {}


async def _refresh_index(entry: TenantIndex, authorization: str | None):
    try:
        rows, _, _ = await all_tenants(authorization)
        entry.rows = rows
        entry.aggregate = summary(rows)
        entry.updated_at = time.monotonic()
        entry.error = None
        entry.retry_after = 0.0
    except UpstreamError as exc:
        entry.error = exc
        entry.retry_after = time.monotonic() + 5.0
        # Never serve cached data after upstream authorization is revoked.
        if exc.status_code in {401, 403}:
            entry.rows = None
    except (KeyError, TypeError, ValueError):
        entry.error = UpstreamError("aggregation", 502, "Invalid upstream user data")
        entry.retry_after = time.monotonic() + 5.0
    finally:
        if entry.task is asyncio.current_task():
            entry.task = None


def _index(authorization: str | None) -> TenantIndex:
    key = hashlib.sha256((authorization or "").encode()).hexdigest()
    if key not in _indexes:
        if len(_indexes) >= MAX_INDEXES:
            oldest = min(_indexes, key=lambda k: _indexes[k].updated_at)
            removed = _indexes.pop(oldest)
            if removed.task:
                removed.task.cancel()
        _indexes[key] = TenantIndex()
    entry = _indexes[key]
    if entry.task is None and time.monotonic() >= entry.retry_after and (entry.rows is None or time.monotonic() - entry.updated_at >= INDEX_TTL):
        entry.task = asyncio.create_task(_refresh_index(entry, authorization))
    return entry


def invalidate_index():
    for entry in _indexes.values():
        entry.updated_at = 0.0
        entry.retry_after = 0.0
        if entry.task:
            entry.task.cancel()
            entry.task = None


async def cached_summary(authorization: str | None) -> dict:
    entry = _index(authorization)
    if entry.task:
        await asyncio.shield(entry.task)
    if entry.error and time.monotonic() - entry.updated_at >= INDEX_TTL:
        raise entry.error
    if entry.rows is None:
        raise entry.error or UpstreamError("aggregation", 503, "User index is warming up; retry shortly")
    return entry.aggregate


async def paginated_tenants(authorization: str | None, *, page=1, page_size=50,
                            organization_id=None, user_status=None, role=None, **filters) -> dict:
    entry = _index(authorization)
    if entry.rows is None:
        raise entry.error or UpstreamError("aggregation", 503, "User index is warming up; retry shortly")
    headers = _headers(authorization)
    async with httpx.AsyncClient() as client:
        rows = entry.rows
        # Preserve Auth's organization-role semantics (roles within the selected
        # organization, global roles otherwise); do not infer them from labels.
        if organization_id is not None or role:
            params = {}
            if organization_id is not None:
                params["organization_id"] = organization_id
            if role:
                params["role"] = role
            allowed = {str(item["id"]) for item in await _directory(client, headers, **params)}
            rows = [row for row in rows if row["tenant_id"] in allowed]
        if user_status:
            rows = [row for row in rows if row.get("status") == user_status]
        rows = filter_sort(rows, **filters)
        selected = rows[(page - 1) * page_size:page * page_size]
        ids = [row["tenant_id"] for row in selected]
        if ids:
            identities, billings, ledgers = await _sources(client, headers, ids)
            selected = [{**row, **tenant_row(identities[row["tenant_id"]], billings.get(row["tenant_id"], {}), ledgers.get(row["tenant_id"], {}))}
                        for row in selected if row["tenant_id"] in identities]
    return {"items": selected, "total": len(rows), "page": page, "page_size": page_size,
            "total_pages": math.ceil(len(rows) / page_size), "index_age_seconds": round(time.monotonic() - entry.updated_at, 1)}
