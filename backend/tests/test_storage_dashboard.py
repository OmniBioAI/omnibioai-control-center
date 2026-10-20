from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
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


def test_mountinfo_parsing_and_read_only_detection():
    parsed = storage.parse_mountinfo(
        "36 25 8:1 / /mnt/archive\\040member ro,nosuid - ext4 /dev/sda1 ro,errors=remount-ro\n"
        "invalid line\n"
    )
    assert "/mnt/archive member" in parsed
    assert parsed["/mnt/archive member"]["filesystem"] == "ext4"
    assert storage._mount_mode(parsed["/mnt/archive member"]["options"]) == "READ_ONLY"
    assert storage._mount_mode(["relatime"]) == "UNKNOWN"


def test_collector_never_substitutes_container_mounts_for_host_mounts(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "HOST_MOUNTINFO", tmp_path / "missing-mountinfo")
    monkeypatch.setattr(storage, "HOST_FSTAB", tmp_path / "missing-fstab")
    with patch.object(storage, "_capacity") as capacity:
        snapshot = storage._collect()
    assert snapshot.sources["mounts"].status == "UNAVAILABLE"
    assert snapshot.sources["configuration"].status == "UNAVAILABLE"
    assert "container mounts were not used" in snapshot.sources["mounts"].detail
    assert snapshot.freshness == "UNKNOWN"
    assert all(device.mount_status == "UNKNOWN" for device in snapshot.physical_devices)
    assert snapshot.archive_pool.pool_status == "UNKNOWN"
    assert not any(alert.id.startswith("mount-missing:") or alert.id.startswith("archive-branch:") for alert in snapshot.alerts)
    capacity.assert_not_called()


def test_collector_uses_only_explicit_host_mount_bind_pair(monkeypatch, tmp_path):
    host_mountinfo = tmp_path / "mountinfo"
    host_fstab = tmp_path / "fstab"
    host_mountinfo.write_text(
        "36 25 8:17 / /mnt/omnibioai-backup20tb rw - ext4 /dev/sdd1 rw\n",
        encoding="utf-8",
    )
    host_fstab.write_text(
        "UUID=example /mnt/omnibioai-backup20tb ext4 defaults 0 2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(storage, "HOST_MOUNTINFO", host_mountinfo)
    monkeypatch.setattr(storage, "HOST_FSTAB", host_fstab)
    with patch.object(storage, "_capacity") as capacity:
        snapshot = storage._collect()
    backup = next(device for device in snapshot.physical_devices if device.role == "backup")
    assert snapshot.sources["mounts"].status == "PARTIAL"
    assert "host PID 1 mountinfo bind" in snapshot.sources["mounts"].detail
    assert backup.mount_status == "MOUNTED"
    assert backup.filesystem == "ext4"
    assert backup.total_bytes is None
    assert snapshot.archive_pool.configured_source == "Host /etc/fstab read-only bind"
    capacity.assert_not_called()


def test_device_identity_uses_kernel_device_number_with_duplicate_models(monkeypatch):
    monkeypatch.setattr(storage, "_read_uuid_map", lambda: {"8:1": "fs-primary", "8:17": "fs-backup"})
    monkeypatch.setattr(storage, "_read_sysfs_device", lambda _device: ("ACASIS enclosure", "/sys/devices/usb1/1-1"))
    monkeypatch.setattr(storage, "_capacity", lambda _path: (100, 50, 50, 50.0))
    mounts = {
        "/mnt/wdpro26tb": {"major_minor": "8:1", "options": ["rw"], "super_options": ["rw"], "filesystem": "ext4", "source": "/dev/sde1"},
        "/mnt/omnibioai-backup20tb": {"major_minor": "8:17", "options": ["rw"], "super_options": ["rw"], "filesystem": "ext4", "source": "/dev/sdd1"},
    }
    records = storage._device_records(mounts, {})
    by_role = {record.role: record for record in records}
    assert by_role["primary"].device_identity == by_role["backup"].device_identity
    assert by_role["primary"].filesystem_uuid == "fs-primary"
    assert by_role["backup"].filesystem_uuid == "fs-backup"


def test_fstab_parsing_exposes_configured_policy_and_missing_minimum():
    entry = "/data=RW:/old=RO /archive fuse.mergerfs rw,category.create=ff,x-systemd.requires-mounts-for=/data,x-systemd.requires-mounts-for=/old 0 0"
    parsed = storage.parse_fstab(entry)
    assert parsed["/archive"]["source"] == "/data=RW:/old=RO"
    options = parsed["/archive"]["options"]
    assert "category.create=ff" in options
    assert not any(value.startswith("minfreespace=") for value in options)
    assert sum(value.startswith("x-systemd.requires-mounts-for=") for value in options) == 2


def test_archive_reports_missing_branch_without_inventing_runtime_policy():
    devices = []
    for role, path in storage.MOUNT_ROLES:
        status = "MISSING" if role == "archive-member-a" else "MOUNTED"
        devices.append(storage.DeviceVolume(
            role=role, label=role, mount_point=path, mount_status=status,
            mount_mode="READ_ONLY" if role == "archive-member-a" else "READ_WRITE",
            filesystem="ext4", filesystem_uuid=None, total_bytes=100, available_bytes=40,
        ))
    fstab = storage.parse_fstab(
        "/data=RW:/old=RO /mnt/omnibioai-archive fuse.mergerfs rw,category.create=ff,x-systemd.requires-mounts-for=/old 0 0"
    )
    archive = storage._archive_data(devices, fstab)
    branch = next(item for item in archive.branches if item.role == "archive-member-a")
    assert branch.mount_status == "MISSING"
    assert branch.expected_mode == "UNKNOWN"  # no matching configured branch path
    assert archive.runtime_policy_status == "NOT_VERIFIED"
    assert archive.create_policy == "ff"


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


def test_restic_credentials_missing_returns_unavailable_without_invocation(monkeypatch):
    monkeypatch.delenv("RESTIC_PASSWORD_FILE", raising=False)
    with patch.object(storage, "_bounded_process") as run:
        result = storage._restic_data("2026-10-20T00:00:00+00:00")
    assert result.repository_status == "UNAVAILABLE"
    assert "no Restic command was run" in result.detail
    run.assert_not_called()


def test_collector_does_not_invoke_process_without_restic_credential(monkeypatch):
    monkeypatch.delenv("RESTIC_PASSWORD_FILE", raising=False)
    with patch.object(storage.subprocess, "Popen") as process:
        snapshot = storage._collect()
    process.assert_not_called()
    assert snapshot.readiness_state == "NOT_VERIFIED"
    assert snapshot.sources["docker"].status == "UNAVAILABLE"


def test_restic_failure_never_returns_stderr_or_secret(monkeypatch):
    with tempfile.NamedTemporaryFile() as password_file:
        os.chmod(password_file.name, 0o600)
        monkeypatch.setenv("RESTIC_PASSWORD_FILE", password_file.name)
        with patch.object(storage, "_secure_password_file", return_value=Path(password_file.name)), \
             patch.object(storage.os.path, "isfile", return_value=True), \
             patch.object(storage.os, "access", return_value=True), \
             patch.object(storage.Path, "is_dir", return_value=True), \
             patch.object(storage, "_bounded_process", return_value=(None, "command_failed")):
            result = storage._restic_data("2026-10-20T00:00:00+00:00")
    assert result.repository_status == "UNAVAILABLE"
    assert "stderr is suppressed" in result.detail
    assert "password" not in result.detail.lower()


def test_bounded_process_enforces_timeout_and_output_limit():
    started = time.monotonic()
    text, status = storage._bounded_process(
        [sys.executable, "-c", "import time; time.sleep(2)"], {"PATH": os.environ.get("PATH", "")}, 0.1, 64
    )
    assert text is None and status == "timeout"
    assert time.monotonic() - started < 1.8
    text, status = storage._bounded_process(
        [sys.executable, "-c", "print('x' * 1000)"], {"PATH": os.environ.get("PATH", "")}, 2, 64
    )
    assert text is None and status == "output_limit"


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
    assert alerts[0].source == "statvfs"

