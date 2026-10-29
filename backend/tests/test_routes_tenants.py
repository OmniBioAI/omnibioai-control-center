from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from control_center.api.routes_tenants import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)
ADMIN = {"sub": "1", "permissions": ["manage_all_orgs"]}


def _row(user_id="1", username="maya"):
    return {"tenant_id": user_id, "username": username, "email": f"{username}@example.org", "plan_id": "plus", "membership_status": "active", "effective_plan_id": "plus", "valid_from": None, "valid_until": None, "auto_renew": True, "days_remaining": None, "allocated_bytes": 20_000_000_000, "allocation_source": "plan", "used_bytes": 2_000_000_000, "reserved_bytes": 0, "pct": 10, "storage_status": "ok", "last_plan_change": None, "last_activity_at": None}


def test_rbac_rejects_missing_and_non_platform_admin_tokens():
    assert client.get("/admin/tenants").status_code == 401
    with patch("control_center.core.auth.verify_token", return_value={"sub": "2", "permissions": []}):
        assert client.get("/admin/tenants", headers={"Authorization": "Bearer x"}).status_code == 403


def test_summary_and_filtered_paginated_list():
    rows = [_row("1", "maya"), _row("2", "zed")]
    with patch("control_center.core.auth.verify_token", return_value=ADMIN), patch("control_center.api.routes_tenants.service.all_tenants", AsyncMock(return_value=(rows, {}, {}))):
        summary = client.get("/admin/tenants/summary", headers={"Authorization": "Bearer x"})
        listing = client.get("/admin/tenants?q=zed&page=1&page_size=1", headers={"Authorization": "Bearer x"})
    assert summary.status_code == 200 and summary.json()["tenants_total"] == 2
    assert listing.status_code == 200 and listing.json()["total"] == 1 and listing.json()["items"][0]["tenant_id"] == "2"


def test_detail_not_found_and_mutation_reason_required():
    with patch("control_center.core.auth.verify_token", return_value=ADMIN), patch("control_center.api.routes_tenants.service.tenant_detail", AsyncMock(return_value=None)):
        assert client.get("/admin/tenants/999", headers={"Authorization": "Bearer x"}).status_code == 404
        response = client.post("/admin/tenants/1/recompute-usage", headers={"Authorization": "Bearer x"}, json={"reason": "   "})
    assert response.status_code == 422


def test_override_and_recompute_mutations_return_refreshed_detail():
    detail = {**_row(), "plan_history": [], "override": None, "top_allocations": [], "workflow_output_bytes": 0, "usage_trend_30d": []}
    with patch("control_center.core.auth.verify_token", return_value=ADMIN), patch("control_center.api.routes_tenants.service.mutate", AsyncMock(return_value={} )) as mutate, patch("control_center.api.routes_tenants.service.tenant_detail", AsyncMock(return_value=detail)):
        put = client.put("/admin/tenants/1/storage-override", headers={"Authorization": "Bearer x"}, json={"allocated_bytes": 3_000_000_000, "reason": "research"})
        delete = client.request("DELETE", "/admin/tenants/1/storage-override", headers={"Authorization": "Bearer x"}, json={"reason": "done"})
        recompute = client.post("/admin/tenants/1/recompute-usage", headers={"Authorization": "Bearer x"}, json={"reason": "reconcile"})
    assert put.status_code == delete.status_code == recompute.status_code == 200
    assert [call.args[0] for call in mutate.await_args_list] == ["PUT", "DELETE", "POST"]
