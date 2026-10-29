import asyncio
from datetime import datetime, timedelta, timezone

from control_center.tenants import service
from unittest.mock import AsyncMock


def _identity(user_id="7"):
    return {"user_id": user_id, "username": "maya", "email": "maya@example.org", "last_activity_at": "2026-10-28T00:00:00Z"}


def _billing(**changes):
    value = {"plan_id": "plus", "membership_status": "active", "effective_plan_id": "plus", "plan_source": "stripe", "promo_expires_at": None, "valid_from": "2026-10-01T00:00:00Z", "valid_until": "2026-11-03T00:00:00Z", "auto_renew": True, "override": None, "plan_history": [{"from_plan": "free", "to_plan": "plus", "at": "2026-10-01T00:00:00Z"}]}
    value.update(changes)
    return value


def test_tenant_row_thresholds_validity_and_override_precedence():
    now = datetime(2026, 10, 29, tzinfo=timezone.utc)
    row = service.tenant_row(_identity(), _billing(), {"used_bytes": 16_000_000_000, "reserved_bytes": 12}, now)
    assert row["days_remaining"] == 5
    assert row["pct"] == 80
    assert row["storage_status"] == "near"
    assert row["last_plan_change"]["to_plan"] == "plus"

    overridden = service.tenant_row(_identity(), _billing(override={"allocated_bytes": 10_000_000_000}), {"used_bytes": 11_000_000_000}, now)
    assert overridden["allocation_source"] == "override"
    assert overridden["storage_status"] == "over_allocation"


def test_expired_canceled_unknown_and_missing_memberships_fall_back_to_free():
    now = datetime(2026, 10, 29, tzinfo=timezone.utc)
    expired = service.tenant_row(_identity(), _billing(valid_until="2026-10-20T00:00:00Z", effective_plan_id="free", plan_source="free"), {}, now)
    canceled = service.tenant_row(_identity(), _billing(membership_status="canceled", effective_plan_id="free", plan_source="free"), {}, now)
    unknown = service.tenant_row(_identity(), _billing(plan_id="enterprise", effective_plan_id="enterprise", membership_status="unpaid"), {}, now)
    missing = service.tenant_row(_identity(), {}, {}, now)
    assert all(row["effective_plan_id"] == "free" and row["allocated_bytes"] == 1_000_000_000 for row in (expired, canceled, unknown, missing))
    assert unknown["membership_status"] == "canceled"
    assert missing["membership_status"] == "none"


def test_filter_sort_pagination_inputs_and_summary():
    now = datetime(2026, 10, 29, tzinfo=timezone.utc)
    rows = [
        service.tenant_row(_identity("7"), _billing(), {"used_bytes": 16_000_000_000}, now),
        service.tenant_row({**_identity("8"), "username": "Zed", "email": "zed@example.org"}, _billing(plan_id="pro", effective_plan_id="pro", membership_status="past_due", valid_until="2026-11-20T00:00:00Z"), {"used_bytes": 101_000_000_000}, now),
        service.tenant_row({**_identity("9"), "username": "Promo", "email": "promo@example.org"}, _billing(plan_id="free", effective_plan_id="pro", membership_status="active", plan_source="promo", promo_expires_at="2026-11-03T00:00:00Z"), {}, now),
        service.tenant_row({**_identity("10"), "username": "Paid", "email": "paid@example.org"}, _billing(plan_id="pro", effective_plan_id="pro", plan_source="stripe", promo_expires_at="2026-11-03T00:00:00Z"), {}, now),
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
        calls.append((url, kwargs["json"]))
        key = "user_ids"
        return {"items": [{"user_id": str(value)} for value in kwargs["json"][key]]}
    monkeypatch.setattr(service, "_json", fake_json)
    identities, billings, ledgers = asyncio.run(service._sources(AsyncMock(), {}, [str(i) for i in range(1001)]))
    assert len(identities) == len(billings) == len(ledgers) == 1001
    assert len(calls) == 6
