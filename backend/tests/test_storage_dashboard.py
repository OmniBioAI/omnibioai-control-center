from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import jwt
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from control_center.api import storage_dashboard as storage
from control_center.core.auth import require_permission
from control_center.core.jwt_verify import JWT_SECRET


app = FastAPI()
app.include_router(
    storage.router_storage_dashboard,
    dependencies=[Depends(require_permission("platform.manage_infra"))],
)
client = TestClient(app)
infra_token = jwt.encode({"sub": "storage-test", "permissions": ["platform.manage_infra"]}, JWT_SECRET, algorithm="HS256")
other_admin_token = jwt.encode({"sub": "tenant-admin", "permissions": ["organizations.read"]}, JWT_SECRET, algorithm="HS256")


def test_storage_dashboard_routes_require_infrastructure_permission():
    for route in ("overview", "devices", "archive", "backups", "health", "readiness"):
        assert client.get(f"/storage/{route}").status_code == 401
        assert client.get(f"/storage/{route}", headers={"Authorization": f"Bearer {other_admin_token}"}).status_code == 403


def test_storage_views_report_missing_and_partial_source_evidence(monkeypatch):
    sample = storage.StorageOverview(
        observed_at="2026-10-20T00:00:00+00:00", freshness="CURRENT", sources={},
        physical_devices=[], archive_pool=storage.ArchiveTelemetry(
            pool_mount_point="/pool", pool_status="UNKNOWN", branches=[], create_policy=None,
            min_free_bytes=None, min_free_policy_status="NOT_CONFIGURED", dependencies=[],
            dependency_assessment="NOT_VERIFIED", configured_source="/etc/fstab", dependency_note="Not verified",
            runtime_policy_status="NOT_VERIFIED",
        ),
        backups=storage.BackupTelemetry(
            repository_status="UNAVAILABLE", snapshots=[], schedule_status="UNKNOWN", schedules=[],
            retention_status="UNKNOWN", restore_verification="NOT_VERIFIED",
            observed_at="2026-10-20T00:00:00+00:00", detail="unavailable",
        ), alerts=[], readiness_gates=[], readiness_state="NOT_VERIFIED",
    )
    sample.readiness_gates = [storage.ReadinessGate(
        id="restic-access", label="Restic access", state="PASS", evidence_source="test",
        observed_at=sample.observed_at, explanation="fixture",
    )]
    monkeypatch.setattr(storage, "get_snapshot", lambda: sample)

    overview = storage.storage_overview()
    assert all(source.status == "UNAVAILABLE" for source in overview.sources.values())
    assert overview.readiness_gates[0].state == "BLOCKED"
    assert storage.storage_readiness().gates[0].state == "BLOCKED"
    for response in (storage.storage_devices(), storage.storage_archive(), storage.storage_backups()):
        assert response.source.status == "UNAVAILABLE"
        assert "not reported" in response.source.detail

    partial = storage.SourceState(
        status="PARTIAL", observed_at=sample.observed_at, detail="Some mounts were unavailable"
    )
    sample.sources = {"mounts": partial}
    assert storage.storage_devices().source == partial
    sample.readiness_gates = [storage.ReadinessGate(
        id="mount-integrity", label="Mount integrity", state="PASS", evidence_source="test",
        observed_at=sample.observed_at, explanation="fixture",
    )]
    assert storage.storage_readiness().gates[0].state == "PARTIAL"


def test_storage_overview_and_views_are_read_only_and_typed():
    with patch.object(storage, "_collect") as collect:
        sample = storage.StorageOverview(
            observed_at="2026-10-20T00:00:00+00:00", freshness="CURRENT", sources={},
            physical_devices=[], archive_pool=storage.ArchiveTelemetry(
                pool_mount_point="/pool", pool_status="UNKNOWN", branches=[], create_policy=None,
                min_free_bytes=None, min_free_policy_status="NOT_CONFIGURED", dependencies=[],
                dependency_assessment="NOT_VERIFIED", configured_source="/etc/fstab", dependency_note="Not verified",
                runtime_policy_status="NOT_VERIFIED",
            ),
            backups=storage.BackupTelemetry(
                repository_status="UNAVAILABLE", snapshots=[], schedule_status="UNKNOWN", schedules=[],
                retention_status="UNKNOWN", restore_verification="NOT_VERIFIED",
                observed_at="2026-10-20T00:00:00+00:00", detail="unavailable",
            ), alerts=[], readiness_gates=storage._readiness("2026-10-20T00:00:00+00:00"),
            readiness_state="NOT_VERIFIED",
        )
        collect.return_value = sample
        storage._cache = None
        headers = {"Authorization": f"Bearer {infra_token}"}
        overview = client.get("/storage/overview", headers=headers)
        assert overview.status_code == 200
        assert overview.json()["readiness_state"] == "NOT_VERIFIED"
        devices = client.get("/storage/devices", headers=headers)
        archive = client.get("/storage/archive", headers=headers)
        backups = client.get("/storage/backups", headers=headers)
        assert devices.status_code == archive.status_code == backups.status_code == 200
        assert devices.json()["source"]["status"] == "UNAVAILABLE"
        assert archive.json()["source"]["status"] == "UNAVAILABLE"
        assert backups.json()["source"]["status"] == "UNAVAILABLE"
        assert "not reported" in devices.json()["source"]["detail"]
        assert client.get("/storage/health", headers=headers).status_code == 200
        assert client.get("/storage/readiness", headers=headers).status_code == 200
        assert collect.call_count == 1

        # A present but incomplete source remains PARTIAL instead of being
        # upgraded to AVAILABLE or treated as missing.
        partial_source = storage.SourceState(
            status="PARTIAL", observed_at=sample.observed_at, detail="Some mounts were unavailable"
        )
        collect.return_value = sample.copy(update={"sources": {"mounts": partial_source}})
        storage._cache = None
        partial_devices = client.get("/storage/devices", headers=headers)
        assert partial_devices.status_code == 200
        assert partial_devices.json()["source"]["status"] == "PARTIAL"
        assert partial_devices.json()["source"]["detail"] == partial_source.detail
    storage._cache = None

    empty_repository = storage.BackupTelemetry(
        repository_status="AVAILABLE", snapshot_count=0, snapshots=[], schedule_status="UNKNOWN", schedules=[],
        retention_status="UNKNOWN", restore_verification="NOT_VERIFIED",
        observed_at="2026-10-20T00:00:00+00:00", detail="inventory collected",
    )
    inventory_gate = next(gate for gate in storage._readiness("now", empty_repository) if gate.id == "snapshot-inventory")
    assert inventory_gate.state == "FAIL"


def test_restic_metadata_is_redacted_and_bounded():
    raw = json.dumps([{
        "id": "f" * 64, "short_id": "abc12345", "time": "2026-10-19T10:00:00Z",
        "paths": ["/home/private/user/project/data.bam"], "tags": ["nightly"],
    }])
    snapshots, latest, truncated = storage.parse_restic_snapshots(raw, datetime(2026, 10, 20, tzinfo=timezone.utc))
    assert latest == "2026-10-19T10:00:00Z"
    assert snapshots[0].source_paths == ["…/data.bam"]
    assert "private" not in snapshots[0].source_paths[0]
    assert snapshots[0].age_seconds == 14 * 60 * 60
    assert not truncated
    assert storage.parse_restic_snapshots("not-json")[0] == []


def test_health_alerts_are_current_observations_only():
    device = storage.DeviceVolume(
        role="primary", label="Primary", mount_point="/primary", mount_status="MOUNTED",
        mount_mode="READ_WRITE", utilization_percent=97, health="CRITICAL",
        health_detail="Filesystem utilization is at least 95%",
    )
    archive = storage.ArchiveTelemetry(
        pool_mount_point="/archive", pool_status="MOUNTED", branches=[], create_policy="ff",
        min_free_bytes=None, min_free_policy_status="NOT_CONFIGURED", dependencies=[],
        dependency_assessment="CONFIGURED", configured_source="/etc/fstab", dependency_note="Not verified", runtime_policy_status="NOT_VERIFIED",
    )
    backups = storage.BackupTelemetry(
        repository_status="AVAILABLE", snapshots=[], schedule_status="UNKNOWN", schedules=[],
        retention_status="UNKNOWN", restore_verification="NOT_VERIFIED", observed_at="now", detail="ok",
    )
    alerts = storage._health_alerts([device], archive, backups, "now")
    assert len(alerts) == 1
    assert alerts[0].state == "ACTIVE"
    assert alerts[0].source == "Host storage telemetry snapshot"

