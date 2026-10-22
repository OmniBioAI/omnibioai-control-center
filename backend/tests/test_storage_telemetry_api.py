"""API regressions for the read-only host storage snapshot pipeline."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from control_center.api import storage_dashboard as storage
from control_center.api.storage_telemetry import HostSnapshot, StorageTarget
from control_center.core.auth import require_permission
from control_center.core.jwt_verify import JWT_SECRET


app = FastAPI()
app.include_router(
    storage.router_storage_dashboard,
    dependencies=[Depends(require_permission("platform.manage_infra"))],
)


ROUTES = ("overview", "devices", "archive", "backups", "health", "readiness")


def token(permissions):
    return jwt.encode({"sub": "storage-release-test", "permissions": permissions}, JWT_SECRET, algorithm="HS256")


@pytest.mark.parametrize("scenario", ("fresh", "missing", "stale"))
def test_storage_api_reports_snapshot_scenarios_safely(monkeypatch, scenario):
    now = datetime.now(timezone.utc)
    snapshot = None
    reason = "snapshot file is missing"
    if scenario != "missing":
        observed = now - (timedelta(hours=3) if scenario == "stale" else timedelta(minutes=5))
        snapshot = HostSnapshot.model_validate({
            "schema_version": 1,
            "observed_at": observed.isoformat(),
            "smart": [{
                "role": "backup", "passed": True,
                "attributes": {"5": 0, "197": 0, "198": 0, "199": 0},
                "udma_crc_error_count_rise": False, "error": None,
            }],
            "mounts": {"backup": {"mounted": True, "uuid": "uuid-backup"}},
            "kernel": {"counts": {}, "devices": []},
            "restic": {"snapshots": [], "stats": {}, "error": None},
        })
        reason = None
    monkeypatch.setattr(storage, "load_targets", lambda: [StorageTarget(
        name="Backup", role="backup", host_path="/mnt/backup", expected_filesystem_uuid="uuid-backup",
    )])
    monkeypatch.setattr(storage, "read_host_snapshot", lambda: (snapshot, reason))
    monkeypatch.setattr(storage, "_capacity", lambda _path: (1000, 700, 300, 70.0))
    monkeypatch.setattr(storage, "_cache", None)

    client = TestClient(app)
    headers = {"Authorization": "Bearer " + token(["platform.manage_infra"])}
    responses = {route: client.get("/storage/" + route, headers=headers) for route in ROUTES}
    assert all(response.status_code == 200 for response in responses.values())
    overview = responses["overview"].json()
    assert overview["physical_devices"][0]["mount_point"] == "/mnt/backup"
    assert all(marker not in response.text for response in responses.values()
               for marker in ("RESTIC_PASSWORD_FILE", "private-error-marker", "/run/host-storage/", "docker.sock"))
    assert overview["freshness"] == {"fresh": "CURRENT", "missing": "UNKNOWN", "stale": "STALE"}[scenario]
    assert overview["physical_devices"][0]["used_bytes"] == (None if scenario == "missing" else 700)
    if scenario == "missing":
        assert overview["physical_devices"][0]["health_detail"] == "No data: snapshot file is missing"
        assert overview["backups"]["detail"] == "No data: snapshot file is missing"


@pytest.mark.parametrize("route", ROUTES)
def test_storage_api_checks_authorization_before_collection(monkeypatch, route):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Unauthorized requests must not collect telemetry")

    monkeypatch.setattr(storage, "get_snapshot", forbidden)
    client = TestClient(app)
    assert client.get("/storage/" + route).status_code == 401
    headers = {"Authorization": "Bearer " + token(["organizations.read"])}
    assert client.get("/storage/" + route, headers=headers).status_code == 403
