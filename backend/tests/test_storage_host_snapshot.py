from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from control_center.api import storage_dashboard as dashboard
from control_center.api.storage_telemetry import HostSnapshot, StorageTarget, load_targets, read_host_snapshot


NOW = datetime.now(timezone.utc)


def targets(state: str | None = None) -> list[StorageTarget]:
    return [StorageTarget(name="Backup", role="backup", host_path="/mnt/backup",
                          expected_filesystem_uuid="uuid-backup")]


def snapshot(*, age: timedelta = timedelta(), smart: list[dict] | None = None,
             snapshot_age: timedelta = timedelta(days=1)) -> HostSnapshot:
    return HostSnapshot.model_validate({
        "schema_version": 1,
        "observed_at": (NOW - age).isoformat(),
        "smart": smart or [],
        "mounts": {"backup": {"mounted": True, "uuid": "uuid-backup"}},
        "kernel": {"window_hours": 24, "counts": {"io_errors": 0}, "devices": [], "error": None},
        "restic": {"snapshots": [{
            "id": "abc123", "time": (NOW - snapshot_age).isoformat(), "paths": ["…/data"], "tags": ["daily"],
        }], "stats": {"total_size": 100}, "error": None},
    })


def arrange(monkeypatch, host_snapshot: HostSnapshot | None, error: str | None = None,
            state: str | None = None) -> None:
    monkeypatch.setattr(dashboard, "load_targets", lambda: targets(state))
    monkeypatch.setattr(dashboard, "read_host_snapshot", lambda: (host_snapshot, error))
    monkeypatch.setattr(dashboard, "_capacity", lambda _path: (1000, 400, 600, 40.0))


def test_missing_snapshot_file_shows_one_missing_data_reason(monkeypatch):
    arrange(monkeypatch, None, "snapshot file is missing")
    result = dashboard._collect()
    assert result.freshness == "UNKNOWN"
    assert result.physical_devices[0].used_bytes is None
    assert result.physical_devices[0].health == "UNKNOWN"
    assert result.physical_devices[0].health_detail == "No data: snapshot file is missing"
    assert result.sources["smart"].detail == "No data: snapshot file is missing"
    assert result.backups.detail == "No data: snapshot file is missing"


def test_snapshot_reader_reports_a_missing_file(tmp_path):
    payload, reason = read_host_snapshot(tmp_path / "not-created.json")
    assert payload is None
    assert reason == "snapshot file is missing"


def test_snapshot_older_than_two_hours_is_stale(monkeypatch):
    arrange(monkeypatch, snapshot(age=timedelta(hours=2, seconds=1)))
    result = dashboard._collect()
    assert result.freshness == "STALE"
    assert result.sources["smart"].detail == "Host snapshot is older than 2 hours"


def test_smart_failing_attributes_raise_warning_and_crc_rise_is_note(monkeypatch):
    arrange(monkeypatch, snapshot(smart=[{
        "role": "backup", "passed": True, "attributes": {"5": 1, "197": 2, "198": 3, "199": 4},
        "udma_crc_error_count_rise": True, "error": None,
    }]))
    result = dashboard._collect()
    device = result.physical_devices[0]
    assert device.health == "WARNING"
    assert "5, 197, 198" in device.health_detail
    assert "cable or enclosure" in (device.note or "")


def test_latest_restic_snapshot_older_than_seven_days_warns(monkeypatch):
    arrange(monkeypatch, snapshot(snapshot_age=timedelta(days=8)))
    result = dashboard._collect()
    assert any(alert.id == "restic:snapshot-old" and alert.severity == "WARNING" for alert in result.alerts)


def test_being_replaced_target_is_not_stat_or_smart_queried(monkeypatch):
    monkeypatch.setattr(dashboard, "load_targets", lambda: [StorageTarget(
        name="Primary", role="primary", host_path="/mnt/wdpro26tb",
        expected_filesystem_uuid="uuid-primary", state="being_replaced", mount=False,
    )])
    monkeypatch.setattr(dashboard, "read_host_snapshot", lambda: (snapshot(smart=[{
        "role": "primary", "passed": False, "attributes": {"5": 99}, "error": None,
    }]), None))
    monkeypatch.setattr(dashboard, "_capacity", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not stat primary")))
    result = dashboard._collect()
    device = result.physical_devices[0]
    assert device.operational_state == "being_replaced"
    assert device.note == "This target is being replaced."
    assert device.health == "UNKNOWN"
    assert device.total_bytes is None
    assert not any(alert.affected_device == "Primary" for alert in result.alerts)


@pytest.mark.parametrize("record", (
    {"mounted": False, "uuid": "uuid-other"},
    {"mounted": False, "uuid": None},
    # The host and API configs disagree: the API's expected UUID wins.
    {"mounted": True, "uuid": "uuid-other"},
    {"mounted": True},
))
def test_uuid_mismatch_reports_not_mounted_without_capacity(monkeypatch, record):
    host = snapshot()
    host.mounts["backup"] = record
    arrange(monkeypatch, host)
    monkeypatch.setattr(dashboard, "_capacity", lambda _path: pytest.fail("must not statvfs an unverified mount"))
    result = dashboard._collect()
    device = result.physical_devices[0]
    assert device.mount_status == "MISSING"
    assert device.total_bytes is None
    assert device.health_detail == "Not mounted"


def test_root_target_bind_on_container_root_reports_not_mounted(monkeypatch):
    # The root target gets no st_dev exemption: an absent bind must not report the container's overlay.
    host = snapshot()
    host.mounts["root"] = {"mounted": True, "uuid": "uuid-root"}
    monkeypatch.setattr(dashboard, "load_targets", lambda: [StorageTarget(
        name="Root filesystem", role="root", host_path="/", expected_filesystem_uuid="uuid-root",
    )])
    monkeypatch.setattr(dashboard, "read_host_snapshot", lambda: (host, None))
    monkeypatch.setattr(dashboard.os, "stat", lambda _path: SimpleNamespace(st_dev=42))
    monkeypatch.setattr(dashboard.os, "statvfs", lambda _path: pytest.fail("must reject before statvfs"))
    device = dashboard._collect().physical_devices[0]
    assert device.mount_status == "MISSING"
    assert device.health_detail == "Not mounted"


def test_kernel_counts_raise_one_alert_with_device_names(monkeypatch):
    host = snapshot()
    host.kernel = {"window_hours": 24, "counts": {"io_errors": 3, "resets": 0, "ext4_errors": 1},
                   "devices": ["sdd", "sdd1"], "error": None}
    arrange(monkeypatch, host)
    alerts = [alert for alert in dashboard._collect().alerts if alert.id == "kernel:storage-errors"]
    assert len(alerts) == 1
    assert alerts[0].affected_device == "sdd, sdd1"
    assert alerts[0].evidence == "Storage-related kernel messages in the last 24 hours (ext4 errors: 1, io errors: 3)."


def test_zero_kernel_counts_raise_no_alert(monkeypatch):
    arrange(monkeypatch, snapshot())
    assert not any(alert.id == "kernel:storage-errors" for alert in dashboard._collect().alerts)


def test_bind_sharing_container_root_device_is_not_counted_as_mounted(monkeypatch):
    monkeypatch.setattr(dashboard.os, "stat", lambda _path: SimpleNamespace(st_dev=42))
    monkeypatch.setattr(dashboard.os, "statvfs", lambda _path: (_ for _ in ()).throw(AssertionError("must reject before statvfs")))
    assert dashboard._capacity("/run/storage-targets/backup") == (None, None, None, None)


TARGETS_YAML = """
system:
  storage_targets:
    - {name: Backup, role: backup, host_path: /mnt/backup, expected_filesystem_uuid: uuid-backup}
    - {name: Primary, role: primary, host_path: /mnt/primary, expected_filesystem_uuid: uuid-primary,
       state: being_replaced, mount: false}
"""


def test_load_targets_reads_configured_targets(tmp_path):
    config = tmp_path / "control_center.yaml"
    config.write_text(TARGETS_YAML, encoding="utf-8")
    targets = load_targets(config)
    assert [(item.role, item.mount, item.state) for item in targets] == [
        ("backup", True, None), ("primary", False, "being_replaced"),
    ]
    assert targets[0].collector_path == Path("/run/storage-targets/backup")


@pytest.mark.parametrize("text", (
    TARGETS_YAML.replace("role: primary", "role: backup"),
    TARGETS_YAML.replace("host_path: /mnt/backup", "host_path: relative"),
    TARGETS_YAML.replace("state: being_replaced", "unexpected: true"),
    "system: [not, a, mapping]\n",
    "system: {storage_targets: {role: backup}}\n",
    "- just a list\n",
    "system: {storage_targets: [\n",
))
def test_load_targets_rejects_invalid_configuration(tmp_path, text):
    config = tmp_path / "control_center.yaml"
    config.write_text(text, encoding="utf-8")
    assert load_targets(config) == []


def test_load_targets_tolerates_a_missing_file(tmp_path):
    assert load_targets(tmp_path / "absent.yaml") == []


def test_snapshot_reader_rejects_files_not_owned_by_root(tmp_path):
    # Real file owned by the test user: refused before it is opened.
    path = tmp_path / "storage-telemetry.json"
    path.write_text('{"schema_version": 1, "observed_at": "2026-01-01T00:00:00+00:00"}', encoding="utf-8")
    path.chmod(0o644)
    if os.geteuid() == 0:
        pytest.skip("ownership check cannot be exercised as root")
    assert read_host_snapshot(path) == (None, "snapshot file is not a safe regular file")


@pytest.mark.parametrize("kind", ("symlink", "directory"))
def test_snapshot_reader_rejects_non_regular_files(tmp_path, kind):
    path = tmp_path / "storage-telemetry.json"
    if kind == "symlink":
        target = tmp_path / "real.json"
        target.write_text("{}", encoding="utf-8")
        path.symlink_to(target)
    else:
        path.mkdir()
    assert read_host_snapshot(path) == (None, "snapshot file is not a safe regular file")


STANDBY = {"role": "backup", "device": "/dev/sdd", "state": "standby", "passed": None,
           "attributes": {}, "error": None, "crc_baseline": 4}


def test_standby_disk_is_neutral_not_a_fault(monkeypatch):
    arrange(monkeypatch, snapshot(smart=[STANDBY]))
    result = dashboard._collect()
    device = result.physical_devices[0]
    assert device.power_state == "STANDBY"
    assert device.health == "UNKNOWN"
    assert device.health_detail == "Standby: SMART skipped so the disk is not woken"
    assert device.smart_status == "UNKNOWN"
    assert device.total_bytes == 1000
    assert not [alert for alert in result.alerts if alert.affected_device == "Backup"]


def test_standby_does_not_hide_a_capacity_warning(monkeypatch):
    arrange(monkeypatch, snapshot(smart=[STANDBY]))
    monkeypatch.setattr(dashboard, "_capacity", lambda _path: (1000, 900, 100, 90.0))
    device = dashboard._collect().physical_devices[0]
    assert device.health == "WARNING"
    assert device.power_state == "STANDBY"


def test_active_smart_reading_reports_active_power_state(monkeypatch):
    arrange(monkeypatch, snapshot(smart=[{**STANDBY, "state": "active", "passed": True,
                                          "attributes": {"5": 0, "199": 4}}]))
    device = dashboard._collect().physical_devices[0]
    assert (device.power_state, device.health, device.smart_status) == ("ACTIVE", "HEALTHY", "AVAILABLE")


def test_unresolved_smart_disk_shows_the_collector_reason(monkeypatch):
    arrange(monkeypatch, snapshot(smart=[{"role": "backup", "device": None, "state": None, "passed": None,
                                          "attributes": {}, "error": "filesystem UUID did not resolve to exactly one whole disk"}]))
    device = dashboard._collect().physical_devices[0]
    assert device.health == "UNKNOWN"
    assert device.power_state is None
    assert device.health_detail == "No data: SMART filesystem UUID did not resolve to exactly one whole disk"
