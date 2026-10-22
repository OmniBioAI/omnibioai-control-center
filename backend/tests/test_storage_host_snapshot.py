from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from control_center.api import storage_dashboard as dashboard
from control_center.api.storage_telemetry import HostSnapshot, StorageTarget, load_targets, read_host_snapshot


NOW = datetime.now(timezone.utc)


def targets(state: str | None = None) -> list[StorageTarget]:
    return [StorageTarget(name="Backup", role="backup", host_path="/mnt/backup",
                          expected_filesystem_uuid="11111111-2222-3333-4444-555555555555")]


def snapshot(*, age: timedelta = timedelta(), smart: list[dict] | None = None,
             snapshot_age: timedelta = timedelta(days=1)) -> HostSnapshot:
    return HostSnapshot.model_validate({
        "schema_version": 1,
        "observed_at": (NOW - age).isoformat(),
        "smart": smart or [],
        "mounts": {"backup": {"mounted": True, "uuid": "11111111-2222-3333-4444-555555555555"}},
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
        expected_filesystem_uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", state="being_replaced", mount=False,
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
    {"mounted": False, "uuid": "00000000-0000-0000-0000-00000000beef"},
    {"mounted": False, "uuid": None},
    # The host and API configs disagree: the API's expected UUID wins.
    {"mounted": True, "uuid": "00000000-0000-0000-0000-00000000beef"},
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
    host.mounts["root"] = {"mounted": True, "uuid": "99999999-8888-7777-6666-555555555555"}
    monkeypatch.setattr(dashboard, "load_targets", lambda: [StorageTarget(
        name="Root filesystem", role="root", host_path="/", expected_filesystem_uuid="99999999-8888-7777-6666-555555555555",
    )])
    monkeypatch.setattr(dashboard, "read_host_snapshot", lambda: (host, None))
    monkeypatch.setattr(dashboard, "_device_id", lambda _path: 42)
    monkeypatch.setattr(dashboard, "_filesystem_stats", lambda _path: pytest.fail("must reject before statvfs"))
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
    monkeypatch.setattr(dashboard, "_device_id", lambda _path: 42)
    monkeypatch.setattr(dashboard, "_filesystem_stats", lambda _path: pytest.fail("must reject before statvfs"))
    assert dashboard._capacity("/run/storage-targets/backup") == (None, None, None, None)


TARGETS_YAML = """
system:
  storage_targets:
    - {name: Backup, role: backup, host_path: /mnt/backup, expected_filesystem_uuid: 11111111-2222-3333-4444-555555555555}
    - {name: Primary, role: primary, host_path: /mnt/primary, expected_filesystem_uuid: aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee,
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


A22, DATA, B2 = "/mnt/omnibioai-archive22tb", "/media/manish/omnibioai-data", "/mnt/omnibioai-archive2tb-b"
POOL_TARGETS = [
    StorageTarget(name="Archive", role="archive", host_path=A22,
                  expected_filesystem_uuid="6a805bb7-2513-435f-9cd4-b9970a0e4fc4"),
    StorageTarget(name="OmniBioAI data 2 TB", role="data2tb", host_path=DATA,
                  expected_filesystem_uuid="39b9324a-640e-4d64-9980-b1f1c9d5578b", read_only=True),
    StorageTarget(name="Archive 2 TB B", role="archive2tb-b", host_path=B2,
                  expected_filesystem_uuid="6A7F-D1A6", read_only=True),
    StorageTarget(name="Archive pool", role="archive-pool", kind="mergerfs", host_path="/mnt/omnibioai-archive",
                  branches=[A22, DATA, B2]),
]
CAPACITY = {  # collector bind path -> (total, used, available, percent)
    "/run/storage-targets/archive": (20_000, 2_400, 17_600, 12.0),
    "/run/storage-targets/data2tb": (1_800, 1_746, 54, 97.0),
    "/run/storage-targets/archive2tb-b": (1_900, 1_786, 114, 94.0),
    "/run/storage-targets/archive-pool": (23_700, 5_932, 17_768, 25.0),
}


def pool_snapshot(branches=("archive", "data2tb", "archive2tb-b"), fstype="fuse.mergerfs", unreadable=()) -> HostSnapshot:
    modes = {"archive": "RW", "data2tb": "RO", "archive2tb-b": "RO"}
    return HostSnapshot.model_validate({
        "schema_version": 1, "observed_at": NOW.isoformat(),
        "smart": [{"role": role, "state": "active", "type": "sat", "passed": True,
                   "attributes": {"5": 0, "197": 0, "198": 0, "199": 0}, "temperature": 33, "error": None}
                  for role in ("archive", "data2tb", "archive2tb-b")],
        "mounts": {
            "archive": {"mounted": True, "uuid": "6a805bb7-2513-435f-9cd4-b9970a0e4fc4", "fstype": "ext4", "read_only": False},
            "data2tb": {"mounted": True, "uuid": "39b9324a-640e-4d64-9980-b1f1c9d5578b", "fstype": "ext4", "read_only": True},
            "archive2tb-b": {"mounted": True, "uuid": "6A7F-D1A6", "fstype": "exfat", "read_only": True},
            "archive-pool": {"kind": "mergerfs", "fstype": fstype,
                             "mounted": fstype == "fuse.mergerfs" and list(branches) == ["archive", "data2tb", "archive2tb-b"],
                             "branches": [{"role": role, "mode": modes.get(role)} for role in branches],
                             "create_policy": None if "create_policy" in unreadable else "ff",
                             "min_free_bytes": None if "min_free_bytes" in unreadable else 4294967295,
                             "version": "2.33.5", "unreadable": list(unreadable), "error": None},
        },
        "kernel": {"counts": {}, "devices": []},
        "restic": {"snapshots": [], "stats": None, "error": None},
    })


def arrange_pool(monkeypatch, host):
    monkeypatch.setattr(dashboard, "load_targets", lambda: POOL_TARGETS)
    monkeypatch.setattr(dashboard, "read_host_snapshot", lambda: (host, None))
    monkeypatch.setattr(dashboard, "_capacity", lambda path: CAPACITY[path])


def test_read_only_disks_never_raise_a_capacity_warning(monkeypatch):
    arrange_pool(monkeypatch, pool_snapshot())
    result = dashboard._collect()
    by_role = {device.role: device for device in result.physical_devices}
    data = by_role["data2tb"]
    assert (data.utilization_percent, data.health, data.read_only, data.mount_mode) == (97.0, "HEALTHY", True, "READ_ONLY")
    assert data.health_detail == "Read-only; capacity is shown without warnings"
    assert by_role["archive2tb-b"].health == "HEALTHY"
    assert not result.alerts


def test_snapshot_fills_filesystem_identity_and_host_mount_mode(monkeypatch):
    arrange_pool(monkeypatch, pool_snapshot())
    by_role = {device.role: device for device in dashboard._collect().physical_devices}
    exfat = by_role["archive2tb-b"]
    assert (exfat.filesystem, exfat.filesystem_uuid, exfat.device_identity) == ("exfat", "6A7F-D1A6", "6A7F-D1A6")
    assert by_role["archive"].mount_mode == "READ_WRITE"
    assert by_role["archive"].smart_attributes == {"5": 0, "197": 0, "198": 0, "199": 0}
    assert by_role["archive"].temperature_celsius == 33 and by_role["archive"].smart_passed is True


def test_verified_pool_reports_total_and_ordered_member_rows(monkeypatch):
    arrange_pool(monkeypatch, pool_snapshot())
    result = dashboard._collect()
    pool = result.archive_pool
    assert "archive-pool" not in {device.role for device in result.physical_devices}
    assert {device.role: device.pool_role for device in result.physical_devices} == {
        "archive": "archive-pool", "data2tb": "archive-pool", "archive2tb-b": "archive-pool"}
    assert (pool.pool_status, pool.total_bytes, pool.used_bytes, pool.available_bytes) == ("MOUNTED", 23_700, 5_932, 17_768)
    assert pool.pool_detail is None
    assert (pool.mergerfs_version, pool.unreadable_settings) == ("2.33.5", [])
    assert [(b.role, b.observed_mode, b.read_only, b.used_bytes) for b in pool.branches] == [
        ("archive", "READ_WRITE", False, 2_400), ("data2tb", "READ_ONLY", True, 1_746), ("archive2tb-b", "READ_ONLY", True, 1_786)]
    assert (pool.create_policy, pool.min_free_bytes, pool.runtime_policy_status) == ("ff", 4294967295, "VERIFIED")


@pytest.mark.parametrize(("branches", "fstype", "detail"), (
    (("archive", "data2tb"), "fuse.mergerfs", "Not mounted: mergerfs branches differ from the configuration"),
    (("data2tb", "archive", "archive2tb-b"), "fuse.mergerfs", "Not mounted: mergerfs branches differ from the configuration"),
    (("archive", "unlisted", "archive2tb-b"), "fuse.mergerfs", "Not mounted: mergerfs branches differ from the configuration"),
    (("archive", "data2tb", "archive2tb-b"), "ext4", "Not mounted: not a mergerfs filesystem"),
))
def test_unverified_pool_reports_not_mounted_without_capacity(monkeypatch, branches, fstype, detail):
    host = pool_snapshot(branches=branches, fstype=fstype)
    host.mounts["archive-pool"]["mounted"] = True  # the API re-checks rather than trusting the flag
    arrange_pool(monkeypatch, host)
    pool = dashboard._collect().archive_pool
    assert (pool.pool_status, pool.total_bytes, pool.pool_detail) == ("MISSING", None, detail)


def test_no_pool_configured(monkeypatch):
    arrange(monkeypatch, snapshot())
    pool = dashboard._collect().archive_pool
    assert (pool.pool_mount_point, pool.branches) == ("Not configured", [])


NVME_UUID = "99999999-8888-7777-6666-555555555555"


@pytest.mark.parametrize(("nvme", "health", "detail"), (
    ({"percentage_used": 3, "media_errors": 0, "temperature": 41}, "HEALTHY", "Capacity collected with statvfs from the read-only bind mount"),
    ({"percentage_used": 79, "media_errors": 0, "temperature": 41}, "HEALTHY", "Capacity collected with statvfs from the read-only bind mount"),
    ({"percentage_used": 80, "media_errors": 0, "temperature": 41}, "WARNING", "NVMe endurance used: 80%"),
    ({"percentage_used": 3, "media_errors": 1200, "temperature": 41}, "WARNING", "NVMe media errors: 1,200"),
))
def test_nvme_warns_on_media_errors_or_wear(monkeypatch, nvme, health, detail):
    host = snapshot(smart=[{"role": "root", "device": "/dev/nvme0n1", "state": "active", "type": "nvme",
                            "passed": True, "attributes": {}, "nvme": nvme, "temperature": 41, "error": None}])
    host.mounts["root"] = {"mounted": True, "uuid": NVME_UUID, "fstype": "ext4", "read_only": False}
    monkeypatch.setattr(dashboard, "load_targets", lambda: [StorageTarget(
        name="Root filesystem", role="root", host_path="/", expected_filesystem_uuid=NVME_UUID)])
    monkeypatch.setattr(dashboard, "read_host_snapshot", lambda: (host, None))
    monkeypatch.setattr(dashboard, "_capacity", lambda _path: (1000, 200, 800, 20.0))
    result = dashboard._collect()
    device = result.physical_devices[0]
    assert (device.health, device.health_detail) == (health, detail)
    assert (device.nvme_percentage_used, device.nvme_media_errors, device.temperature_celsius) == (
        nvme["percentage_used"], nvme["media_errors"], 41)
    assert bool(result.alerts) is (health == "WARNING")


def test_restic_stats_come_from_the_snapshot_summary(monkeypatch):
    host = snapshot()
    host.restic["stats"] = {"snapshot_id": "abc123", "total_size": 3089592662016, "total_file_count": 75600000}
    arrange(monkeypatch, host)
    backups = dashboard._collect().backups
    assert (backups.latest_snapshot_size_bytes, backups.latest_snapshot_file_count) == (3089592662016, 75600000)
    assert backups.retention_summary is None


def test_null_restic_stats_are_not_an_error(monkeypatch):
    host = snapshot()
    host.restic["stats"] = None
    arrange(monkeypatch, host)
    backups = dashboard._collect().backups
    assert backups.repository_status == "AVAILABLE"
    assert (backups.latest_snapshot_size_bytes, backups.latest_snapshot_file_count) == (None, None)


@pytest.mark.parametrize("uuid", ("6A7F-D1A6", "6a805bb7-2513-435f-9cd4-b9970a0e4fc4"))
def test_storage_target_accepts_standard_and_short_exfat_uuids(uuid):
    assert StorageTarget(name="x", role="x", host_path="/x", expected_filesystem_uuid=uuid).expected_filesystem_uuid == uuid


@pytest.mark.parametrize("fields", (
    {"expected_filesystem_uuid": "6A7F-D1A"},
    {"expected_filesystem_uuid": "REPLACE_ME"},
    {},
    {"expected_filesystem_uuid": "6A7F-D1A6", "branches": ["/a"]},
    {"kind": "mergerfs", "branches": []},
    {"kind": "mergerfs", "branches": ["relative"]},
    {"kind": "mergerfs", "branches": ["/a"], "expected_filesystem_uuid": "6A7F-D1A6"},
))
def test_storage_target_rejects_invalid_identity(fields):
    with pytest.raises(ValueError):
        StorageTarget(name="x", role="x", host_path="/x", **fields)


def test_unreadable_pool_settings_are_named_once(monkeypatch):
    arrange_pool(monkeypatch, pool_snapshot(unreadable=("create_policy", "min_free_bytes")))
    pool = dashboard._collect().archive_pool
    assert pool.pool_status == "MOUNTED"
    assert (pool.create_policy, pool.min_free_bytes) == (None, None)
    assert pool.unreadable_settings == ["create policy", "minimum free space"]


def test_capacity_reads_a_real_directory_on_its_own_filesystem(monkeypatch, tmp_path):
    assert dashboard._device_id(str(tmp_path)) == os.stat(tmp_path).st_dev
    assert dashboard._filesystem_stats(str(tmp_path)).f_blocks == os.statvfs(tmp_path).f_blocks
    # Pretend the directory is a separate mount so its real statvfs numbers are used.
    monkeypatch.setattr(dashboard, "_device_id", lambda path: 1 if path == "/" else 2)
    total, used, available, percent = dashboard._capacity(str(tmp_path))
    assert total > 0 and 0 <= used <= total and available >= 0 and 0 <= percent <= 100
    assert dashboard._capacity(str(tmp_path / "absent")) == (None, None, None, None)


def test_pool_without_a_snapshot_has_no_data(monkeypatch):
    arrange_pool(monkeypatch, None)
    monkeypatch.setattr(dashboard, "read_host_snapshot", lambda: (None, "snapshot file is missing"))
    pool = dashboard._collect().archive_pool
    assert (pool.pool_status, pool.pool_detail) == ("UNKNOWN", "No data: host snapshot is unavailable")


def test_pool_missing_from_the_snapshot_is_not_mounted(monkeypatch):
    host = pool_snapshot()
    del host.mounts["archive-pool"]
    arrange_pool(monkeypatch, host)
    pool = dashboard._collect().archive_pool
    assert (pool.pool_status, pool.pool_detail) == ("MISSING", "Not mounted")


def test_pool_whose_bind_cannot_be_measured_is_not_mounted(monkeypatch):
    arrange_pool(monkeypatch, pool_snapshot())
    monkeypatch.setattr(dashboard, "_capacity", lambda path: (None, None, None, None) if path.endswith("archive-pool") else CAPACITY[path])
    pool = dashboard._collect().archive_pool
    assert (pool.pool_status, pool.pool_detail, pool.total_bytes) == ("MISSING", "Not mounted", None)


BASIC = {"device": "/dev/sdg", "state": None, "smart_mode": "scsi_health_only", "power_state": "unknown",
         "type": "scsi", "passed": True, "attributes": {}, "checked_at": "2026-10-22T06:00:00+00:00", "error": None}


def basic_pool_snapshot(**overrides) -> HostSnapshot:
    host = pool_snapshot()
    host.smart = [item for item in host.smart if item["role"] not in {"data2tb", "archive2tb-b"}] + [
        {**BASIC, "role": "data2tb", **overrides}, {**BASIC, "role": "archive2tb-b", "device": "/dev/sdh", **overrides}]
    return host


def test_scsi_health_only_disks_are_healthy_and_never_standby_or_missing(monkeypatch):
    arrange_pool(monkeypatch, basic_pool_snapshot())
    result = dashboard._collect()
    by_role = {device.role: device for device in result.physical_devices}
    for role in ("data2tb", "archive2tb-b"):
        device = by_role[role]
        assert (device.health, device.mount_status, device.power_state, device.smart_mode) == (
            "HEALTHY", "MOUNTED", "UNKNOWN", "scsi_health_only")
        assert (device.smart_passed, device.smart_attributes, device.smart_status) == (True, {}, "AVAILABLE")
        assert device.smart_checked_at == "2026-10-22T06:00:00+00:00"
        assert device.health_detail == "Read-only; capacity is shown without warnings"
    assert not result.alerts


def test_failed_scsi_health_check_warns(monkeypatch):
    arrange_pool(monkeypatch, basic_pool_snapshot(passed=False))
    result = dashboard._collect()
    device = {device.role: device for device in result.physical_devices}["data2tb"]
    assert (device.health, device.health_detail) == ("WARNING", "Basic SMART health check failed")
    assert {alert.affected_device for alert in result.alerts} == {"OmniBioAI data 2 TB", "Archive 2 TB B"}


def test_unknown_power_state_is_never_shown_as_standby(monkeypatch):
    arrange_pool(monkeypatch, basic_pool_snapshot(smart_mode="full", state="standby",
                                                  attributes={"5": 0, "197": 0, "198": 0, "199": 0}))
    device = {device.role: device for device in dashboard._collect().physical_devices}["data2tb"]
    assert (device.power_state, device.smart_mode, device.health) == ("UNKNOWN", "full", "HEALTHY")
    assert "Standby" not in device.health_detail
