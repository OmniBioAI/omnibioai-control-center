import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from control_center.tenants import service

PLANS = {"free": 1_000_000_000, "plus": 20_000_000_000, "pro": 100_000_000_000}


def _row(identity, billing, ledger, now):
    return service.tenant_row(identity, billing, {"storage_account_exists": True, "folder_status": "done", **ledger}, now, plans=PLANS)


def _identity(user_id="7"):
    return {"user_id": user_id, "username": "maya", "email": "maya@example.org", "last_activity_at": "2026-10-28T00:00:00Z"}


def _billing(**changes):
    value = {"plan_id": "plus", "membership_status": "active", "effective_plan_id": "plus", "plan_source": "stripe", "promo_expires_at": None, "valid_from": "2026-10-01T00:00:00Z", "valid_until": "2026-11-03T00:00:00Z", "auto_renew": True, "override": None, "plan_history": [{"from_plan": "free", "to_plan": "plus", "at": "2026-10-01T00:00:00Z"}]}
    value.update(changes)
    return value


def test_tenant_row_thresholds_validity_and_override_precedence():
    now = datetime(2026, 10, 29, tzinfo=timezone.utc)
    row = _row(_identity(), _billing(), {"used_bytes": 16_000_000_000, "reserved_bytes": 12}, now)
    assert row["days_remaining"] == 5
    assert row["pct"] == 80
    assert row["storage_status"] == "near"
    assert row["last_plan_change"]["to_plan"] == "plus"

    overridden = _row(_identity(), _billing(override={"allocated_bytes": 10_000_000_000}), {"used_bytes": 11_000_000_000}, now)
    assert overridden["allocation_source"] == "override"
    assert overridden["storage_status"] == "over_allocation"


def test_expired_canceled_unknown_and_missing_memberships_fall_back_to_free():
    now = datetime(2026, 10, 29, tzinfo=timezone.utc)
    expired = _row(_identity(), _billing(valid_until="2026-10-20T00:00:00Z", effective_plan_id="free", plan_source="free"), {}, now)
    canceled = _row(_identity(), _billing(membership_status="canceled", effective_plan_id="free", plan_source="free"), {}, now)
    unknown = _row(_identity(), _billing(plan_id="enterprise", effective_plan_id="enterprise", membership_status="unpaid"), {}, now)
    missing = _row(_identity(), {}, {}, now)
    assert expired["effective_plan_id"] == canceled["effective_plan_id"] == "free"
    assert unknown["effective_plan_id"] is None and missing["effective_plan_id"] is None
    assert missing["storage_status"] == "no_membership"
    assert service.summary([missing], now)["allocated_sum_bytes"] == 0
    assert unknown["membership_status"] == "canceled"
    assert missing["membership_status"] == "none"


def test_filter_sort_pagination_inputs_and_summary():
    now = datetime(2026, 10, 29, tzinfo=timezone.utc)
    rows = [
        _row(_identity("7"), _billing(), {"used_bytes": 16_000_000_000}, now),
        _row({**_identity("8"), "username": "Zed", "email": "zed@example.org"}, _billing(plan_id="pro", effective_plan_id="pro", membership_status="past_due", valid_until="2026-11-20T00:00:00Z"), {"used_bytes": 101_000_000_000}, now),
        _row({**_identity("9"), "username": "Promo", "email": "promo@example.org"}, _billing(plan_id="free", effective_plan_id="pro", membership_status="active", plan_source="promo", promo_expires_at="2026-11-03T00:00:00Z"), {}, now),
        _row({**_identity("10"), "username": "Paid", "email": "paid@example.org"}, _billing(plan_id="pro", effective_plan_id="pro", plan_source="stripe", promo_expires_at="2026-11-03T00:00:00Z"), {}, now),
    ]
    assert service.filter_sort(rows, plan="plus", status="active", validity="expiring_7d", storage_status="near", q="MAYA", sort="-used_bytes")[0]["tenant_id"] == "7"
    assert service.filter_sort(rows, validity="expiring_30d", q="8", sort="not_a_column")[0]["tenant_id"] == "8"
    assert service.filter_sort(rows, plan_source="promo")[0]["tenant_id"] == "9"
    aggregate = service.summary(rows, now)
    assert aggregate["tenants_total"] == 4
    assert aggregate["per_plan"] == {"free": 0, "plus": 1, "pro": 3}
    assert aggregate["past_due"] == 1 and aggregate["over_allocation"] == 1 and aggregate["expiring_7d"] == 3
    assert aggregate["promos_active"] == 2 and aggregate["promos_expiring_7d"] == 2


def test_parse_naive_and_headers():
    assert service._parse("2026-10-29T00:00:00").tzinfo == timezone.utc
    assert service._parse(None) is None
    assert service._headers(None) == {"Content-Type": "application/json"}
    assert service._headers("Bearer x")["Authorization"] == "Bearer x"


def test_sources_chunks_large_tenant_sets(monkeypatch):
    calls = []
    async def fake_json(client, method, url, name, headers, **kwargs):
        calls.append((url, kwargs.get("json")))
        if method == "GET":
            return {"plans": {key: {"storage_quota_bytes": value} for key, value in PLANS.items()}}
        key = "user_ids"
        return {"items": [{"user_id": str(value)} for value in kwargs["json"][key]]}
    monkeypatch.setattr(service, "_json", fake_json)
    identities, billings, ledgers, plans = asyncio.run(service._sources(AsyncMock(), {}, [str(i) for i in range(1001)]))
    assert len(identities) == len(billings) == len(ledgers) == 1001
    assert plans == PLANS and len(calls) == 7


def test_detail_resolves_history_actors_in_one_deduplicated_batch(monkeypatch):
    calls = []
    async def fake_json(client, method, url, name, headers, **kwargs):
        if name == "auth-service":
            ids = kwargs["json"]["user_ids"]
            calls.append(ids)
            if ids == [7]:
                return {"items": [_identity()]}
            assert ids == [42, 43, 99]
            return {"items": [{"user_id": "42", "email": "admin@example.org", "username": "admin"},
                              {"user_id": "43", "email": "", "username": "operator"}]}
        if name == "billing-service":
            if url.endswith("/plans/catalog"):
                return {"plans": {key: {"storage_quota_bytes": value} for key, value in PLANS.items()}}
            return _billing(plan_history=[{"from_plan": "free", "to_plan": "plus", "at": "2026-10-01T00:00:00Z", "actor": a} for a in ["user:42", "user:42", "user:43", "user:99", "stripe", None]])
        return {}
    monkeypatch.setattr(service, "_json", fake_json)
    detail = asyncio.run(service.tenant_detail("7", None))
    assert calls == [[7], [42, 43, 99]]
    history = detail["plan_history"]
    assert [h["actor_display"] for h in history] == ["admin@example.org", "admin@example.org", "operator", None, None, None]
    assert history[0]["actor"] == "user:42"


def test_detail_keeps_audit_actor_when_identity_lookup_fails(monkeypatch):
    async def fake_json(client, method, url, name, headers, **kwargs):
        if name == "auth-service":
            if kwargs["json"]["user_ids"] == [7]:
                return {"items": [_identity()]}
            raise service.UpstreamError("auth-service", 503, "unavailable")
        if name == "billing-service":
            if url.endswith("/plans/catalog"):
                return {"plans": {key: {"storage_quota_bytes": value} for key, value in PLANS.items()}}
            return _billing(plan_history=[{"from_plan": "free", "to_plan": "plus", "at": "2026-10-01T00:00:00Z", "actor": "user:42"}])
        return {}
    monkeypatch.setattr(service, "_json", fake_json)
    detail = asyncio.run(service.tenant_detail("7", None))
    assert detail["plan_history"][0]["actor"] == "user:42"
    assert detail["plan_history"][0]["actor_display"] is None


@pytest.mark.asyncio
async def test_json_normalizes_transport_http_and_decode_failures():
    request = httpx.Request("GET", "http://upstream.test/value")
    client = AsyncMock()
    client.request.side_effect = httpx.ConnectError("offline", request=request)
    with pytest.raises(service.UpstreamError, match="billing-service unavailable") as unavailable:
        await service._json(client, "GET", str(request.url), "billing-service", {})
    assert unavailable.value.status_code == 503

    client.request.side_effect = None
    client.request.return_value = httpx.Response(409, request=request, json={"detail": "conflict"})
    with pytest.raises(service.UpstreamError, match="conflict") as conflict:
        await service._json(client, "GET", str(request.url), "billing-service", {})
    assert conflict.value.status_code == 409

    client.request.return_value = httpx.Response(500, request=request, text="not-json")
    with pytest.raises(service.UpstreamError, match="billing-service returned 500"):
        await service._json(client, "GET", str(request.url), "billing-service", {})

    client.request.return_value = httpx.Response(200, request=request, text="not-json")
    with pytest.raises(service.UpstreamError, match="invalid JSON") as invalid:
        await service._json(client, "GET", str(request.url), "billing-service", {})
    assert invalid.value.status_code == 502


@pytest.mark.asyncio
async def test_directory_paginates_and_all_user_ids_are_strings(monkeypatch):
    calls = []

    async def fake_json(client, method, url, name, headers, **kwargs):
        page = kwargs["params"]["page"]
        calls.append(page)
        return {"items": [{"id": page}], "total_pages": 2}

    monkeypatch.setattr(service, "_json", fake_json)
    assert await service._all_user_ids(AsyncMock(), {}) == ["1", "2"]
    assert calls == [1, 2]


@pytest.mark.asyncio
async def test_empty_directory_and_missing_detail_are_real_missing_states(monkeypatch):
    monkeypatch.setattr(service, "_directory", AsyncMock(return_value=[]))
    assert await service.all_tenants("Bearer admin") == ([], {}, {})

    monkeypatch.setattr(service, "_json", AsyncMock(return_value={"items": []}))
    assert await service.tenant_detail("404", "Bearer admin") is None


@pytest.mark.asyncio
async def test_refresh_index_records_success_upstream_denial_and_bad_payload(monkeypatch):
    entry = service.TenantIndex()
    monkeypatch.setattr(service, "all_tenants", AsyncMock(return_value=([_row(_identity(), _billing(), {}, datetime.now(timezone.utc))], {}, {})))
    await service._refresh_index(entry, "Bearer admin")
    assert entry.rows and entry.aggregate["tenants_total"] == 1
    assert entry.error is None and entry.retry_after == 0

    denied = service.UpstreamError("auth-service", 403, "denied")
    monkeypatch.setattr(service, "all_tenants", AsyncMock(side_effect=denied))
    await service._refresh_index(entry, "Bearer admin")
    assert entry.rows is None and entry.error is denied and entry.retry_after > 0

    monkeypatch.setattr(service, "all_tenants", AsyncMock(side_effect=KeyError("user_id")))
    await service._refresh_index(entry, "Bearer admin")
    assert entry.error.service == "aggregation" and entry.error.status_code == 502


def test_row_exposes_no_account_folder_pending_and_invalid_membership_states():
    now = datetime(2026, 10, 29, tzinfo=timezone.utc)
    no_account = service.tenant_row(_identity(), _billing(), {}, now, plans=PLANS)
    folder_pending = service.tenant_row(
        _identity(), _billing(), {"storage_account_exists": True, "folder_status": "pending"}, now, plans=PLANS
    )
    invalid = service.tenant_row(
        _identity(), _billing(effective_plan_id="retired"), {"storage_account_exists": True}, now, plans=PLANS
    )
    assert no_account["storage_status"] == "no_account"
    assert folder_pending["storage_status"] == "folder_pending"
    assert invalid["storage_status"] == "invalid_membership"


@pytest.mark.asyncio
async def test_all_tenants_combines_directory_and_resolved_sources(monkeypatch):
    directory = [{"id": 7, "status": "active"}]
    monkeypatch.setattr(service, "_directory", AsyncMock(return_value=directory))
    monkeypatch.setattr(
        service,
        "_sources",
        AsyncMock(return_value=({"7": _identity()}, {"7": _billing()}, {"7": {"storage_account_exists": True, "folder_status": "done"}}, PLANS)),
    )
    rows, billings, ledgers = await service.all_tenants("Bearer admin")
    assert rows[0]["tenant_id"] == "7" and rows[0]["status"] == "active"
    assert billings["7"]["plan_id"] == "plus" and ledgers["7"]["folder_status"] == "done"


def test_filter_sort_supports_history_dict_values():
    rows = [{"tenant_id": "7", "username": "maya", "last_plan_change": {"at": "2026-10-01T00:00:00Z"}}]
    assert service.filter_sort(rows, sort="last_plan_change") == rows


@pytest.mark.asyncio
async def test_index_eviction_invalidation_and_warmup(monkeypatch):
    old_task = Mock()
    old = service.TenantIndex(rows=[], updated_at=1.0, task=old_task)
    monkeypatch.setattr(service, "MAX_INDEXES", 1)
    monkeypatch.setattr(service, "_indexes", {"old": old})
    created = service._index("Bearer new")
    old_task.cancel.assert_called_once_with()
    assert created.task is not None
    created.task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await created.task

    pending = Mock()
    created.task = pending
    service.invalidate_index()
    pending.cancel.assert_called_once_with()
    assert created.task is None and created.updated_at == 0 and created.retry_after == 0

    monkeypatch.setattr(service, "_index", lambda authorization: service.TenantIndex())
    with pytest.raises(service.UpstreamError, match="warming up") as warming:
        await service.cached_summary("Bearer admin")
    assert warming.value.status_code == 503
