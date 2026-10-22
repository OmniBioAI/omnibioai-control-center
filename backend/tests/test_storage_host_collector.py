from __future__ import annotations

import importlib.util
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[2] / "ops/storage-telemetry/collect-storage-telemetry.py"
FIXTURES = Path(__file__).parent / "fixtures/smartctl"
NOW = datetime(2026, 10, 22, 6, 0, tzinfo=timezone.utc)
SPEC = importlib.util.spec_from_file_location("storage_host_collector", SCRIPT)
assert SPEC and SPEC.loader
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


def test_mount_check_matches_configured_uuid_with_findmnt(monkeypatch, tmp_path):
    mountpoint = str(tmp_path)  # a real directory, so the read-only flag comes from a real statvfs
    monkeypatch.setenv("STORAGE_TELEMETRY_TARGETS", f"backup|{mountpoint}|12345678-aaaa-bbbb-cccc-1234567890ab")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return "12345678-AAAA-bbbb-cccc-1234567890ab ext4\n", None

    monkeypatch.setattr(collector, "run", fake_run)
    assert collector.mount_records() == {"backup": {
        "mounted": True, "uuid": "12345678-AAAA-bbbb-cccc-1234567890ab", "fstype": "ext4", "read_only": False}}
    assert calls == [["findmnt", "-n", "-o", "UUID,FSTYPE", mountpoint]]

    monkeypatch.setattr(collector, "run", lambda *_args, **_kwargs: ("00000000-0000-0000-0000-000000000000 ext4\n", None))
    assert collector.mount_records()["backup"] == {
        "mounted": False, "uuid": "00000000-0000-0000-0000-000000000000", "fstype": "ext4", "read_only": None}

    # A filesystem without a UUID (mergerfs, tmpfs) prints only its type.
    monkeypatch.setattr(collector, "run", lambda *_args, **_kwargs: ("     fuse.mergerfs\n", None))
    assert collector.mount_records()["backup"] == {"mounted": False, "uuid": None, "fstype": "fuse.mergerfs", "read_only": None}

    # findmnt exits 1 when the path is not a mountpoint.
    monkeypatch.setattr(collector, "run", lambda *_args, **_kwargs: (None, "command exited with status 1"))
    assert collector.mount_records()["backup"] == {"mounted": False, "uuid": None, "fstype": None, "read_only": None}


def test_short_exfat_uuid_is_accepted_and_matched(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_TELEMETRY_TARGETS", f"archive2tb-b|{tmp_path}|6A7F-D1A6")
    monkeypatch.setattr(collector, "run", lambda *_args, **_kwargs: ("6A7F-D1A6                            exfat\n", None))
    assert collector.mount_records()["archive2tb-b"]["mounted"] is True


@pytest.mark.parametrize("uuid", ("12345678-aaaa", "6A7F-D1A", "6A7FD1A6", "not-a-uuid-at-all", "../etc"))
def test_target_list_rejects_malformed_uuids(monkeypatch, uuid):
    monkeypatch.setenv("STORAGE_TELEMETRY_TARGETS", f"backup|/mnt/backup|{uuid}")
    assert collector.target_list() == []


POOL = "archive-pool|/mnt/pool|/mnt/a:/mnt/b:/mnt/c"
TARGETS = ("big|/mnt/a|11111111-2222-3333-4444-555555555555 small-a|/mnt/b|6A7F-D1A6 "
           "small-b|/mnt/c|22222222-3333-4444-5555-666666666666")
BRANCHES = "/mnt/a=RW:/mnt/b=RO:/mnt/c=RO"
SETTINGS = {"category.create": "ff", "minfreespace": "4294967295", "version": "2.33.5"}


def fake_pool(monkeypatch, fstype="fuse.mergerfs", branches=BRANCHES, settings=SETTINGS):
    monkeypatch.setenv("STORAGE_TELEMETRY_POOLS", POOL)
    monkeypatch.setenv("STORAGE_TELEMETRY_TARGETS", TARGETS)
    calls = []

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        return f"{fstype}\n", None

    values = {"branches": branches, **settings}
    monkeypatch.setattr(collector, "run", fake_run)
    monkeypatch.setattr(collector, "mergerfs_value", lambda mountpoint, key: (calls.append(["xattr", mountpoint, key]), values.get(key))[1])
    return calls


def test_pool_is_verified_by_type_and_exact_branch_list_and_stores_roles_not_paths(monkeypatch):
    calls = fake_pool(monkeypatch)
    record = collector.pool_records()["archive-pool"]
    assert record == {
        "kind": "mergerfs", "fstype": "fuse.mergerfs", "mounted": True, "error": None, "unreadable": [],
        "branches": [{"role": "big", "mode": "RW"}, {"role": "small-a", "mode": "RO"}, {"role": "small-b", "mode": "RO"}],
        "create_policy": "ff", "min_free_bytes": 4294967295, "version": "2.33.5",
    }
    assert "/mnt/" not in json.dumps(record)
    assert calls[0] == ["findmnt", "-n", "-o", "FSTYPE", "/mnt/pool"]
    assert {tuple(call[2:]) for call in calls if call[0] == "xattr"} == {
        ("branches",), ("category.create",), ("minfreespace",), ("version",)}


@pytest.mark.parametrize("branches", (
    "/mnt/a=RW:/mnt/b=RO",                       # a branch is missing
    "/mnt/a=RW:/mnt/b=RO:/mnt/c=RO:/mnt/d=RO",   # an extra branch
    "/mnt/b=RO:/mnt/a=RW:/mnt/c=RO",             # same paths, different order
    "/mnt/a=RW:/mnt/b=RO:/mnt/cc=RO",
    None,                                        # control file unreadable
))
def test_pool_with_different_branches_is_not_mounted(monkeypatch, branches):
    fake_pool(monkeypatch, branches=branches)
    record = collector.pool_records()["archive-pool"]
    assert record["mounted"] is False
    assert "/mnt/" not in json.dumps(record)


def test_unknown_branch_is_stored_as_unlisted(monkeypatch):
    fake_pool(monkeypatch, branches="/mnt/a=RW:/home/someone/private=RO:/mnt/c=RO")
    record = collector.pool_records()["archive-pool"]
    assert [branch["role"] for branch in record["branches"]] == ["big", "unlisted", "small-b"]
    assert "private" not in json.dumps(record)


def test_unreadable_settings_are_listed_once_each(monkeypatch):
    fake_pool(monkeypatch, settings={"category.create": "ff", "minfreespace": "lots"})
    record = collector.pool_records()["archive-pool"]
    assert record["mounted"] is True
    assert (record["min_free_bytes"], record["version"]) == (None, None)
    assert record["unreadable"] == ["min_free_bytes", "version"]


def test_non_mergerfs_mount_is_rejected_without_reading_the_control_file(monkeypatch):
    calls = fake_pool(monkeypatch, fstype="ext4")
    record = collector.pool_records()["archive-pool"]
    assert record["mounted"] is False and record["error"] == "not a mergerfs mount"
    assert not [call for call in calls if call[0] == "xattr"]


def test_pool_list_rejects_malformed_entries(monkeypatch):
    monkeypatch.setenv("STORAGE_TELEMETRY_POOLS", "Bad|/mnt/pool|/mnt/a pool|relative|/mnt/a ok|/mnt/pool|/mnt/a:bad")
    assert collector.pool_list() == []


def test_kernel_summary_persists_only_counts_and_device_names(monkeypatch):
    lines = "\n".join((
        "blk_update_request: I/O error, dev sdd, sector 42 serial=SECRET-123 /home/private/host",
        "EXT4-fs error (device sda1): ext4_lookup: UUID 9d872bab-secret",
        "sd 2:0:0:0: [sdd] tag#0 device reset",
        "usb 1-1: new high-speed USB device sdz unrelated",
    ))
    monkeypatch.setattr(collector, "run", lambda *_args, **_kwargs: (lines, None))
    result = collector.kernel_summary()
    assert result["counts"] == {"io_errors": 1, "resets": 1, "ext4_errors": 1}
    assert result["devices"] == ["sda1", "sdd"]
    encoded = json.dumps(result)
    for marker in ("SECRET-123", "/home/private", "9d872bab", "ext4_lookup", "sector"):
        assert marker not in encoded


def password_file(tmp_path: Path, mode: int) -> Path:
    path = tmp_path / "restic-password"
    path.write_text("not-a-real-password\n", encoding="utf-8")
    path.chmod(mode)
    return path


def test_restic_runs_only_snapshots_and_takes_stats_from_the_newest_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("RESTIC_PASSWORD_FILE", str(password_file(tmp_path, 0o400)))
    monkeypatch.setenv("RESTIC_REPOSITORY", "/backup/restic")
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-reach-restic")
    snapshots = [
        {"short_id": "old", "time": "2026-10-01T00:00:00Z", "paths": ["/data/a"],
         "summary": {"total_bytes_processed": 1, "total_files_processed": 1}},
        {"short_id": "new", "time": "2026-10-20T00:00:00Z", "paths": ["/data/b"], "tags": ["daily"],
         "summary": {"total_bytes_processed": 3089592662016, "total_files_processed": 75600000}},
    ]
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs["timeout"]))
        assert "UNRELATED_SECRET" not in kwargs["env"]
        return json.dumps(snapshots), None

    monkeypatch.setattr(collector, "run", fake_run)
    result = collector.restic_snapshot()
    assert calls == [(["restic", "snapshots", "--json", "--no-lock"], 600)]
    assert result["error"] is None
    assert result["stats"] == {"snapshot_id": "new", "total_size": 3089592662016, "total_file_count": 75600000}
    assert [item["id"] for item in result["snapshots"]] == ["old", "new"]
    assert "summary" not in json.dumps(result["snapshots"])


@pytest.mark.parametrize("newest", (
    {"short_id": "new", "time": "2026-10-20T00:00:00Z"},                                    # restic < 0.17
    {"short_id": "new", "time": "2026-10-20T00:00:00Z", "summary": {"total_bytes_processed": -1}},
    {"short_id": "new", "time": "2026-10-20T00:00:00Z", "summary": "corrupt"},
))
def test_missing_or_invalid_summary_reports_null_stats_without_error(monkeypatch, tmp_path, newest):
    monkeypatch.setenv("RESTIC_PASSWORD_FILE", str(password_file(tmp_path, 0o400)))
    older = {"short_id": "old", "time": "2026-10-01T00:00:00Z",
             "summary": {"total_bytes_processed": 1, "total_files_processed": 1}}
    monkeypatch.setattr(collector, "run", lambda *_args, **_kwargs: (json.dumps([older, newest]), None))
    result = collector.restic_snapshot()
    assert result["stats"] is None and result["error"] is None
    assert len(result["snapshots"]) == 2


def test_empty_repository_reports_null_stats(monkeypatch, tmp_path):
    monkeypatch.setenv("RESTIC_PASSWORD_FILE", str(password_file(tmp_path, 0o400)))
    monkeypatch.setattr(collector, "run", lambda *_args, **_kwargs: ("[]", None))
    assert collector.restic_snapshot() == {"snapshots": [], "stats": None, "error": None}


@pytest.mark.parametrize("setup", ("group-readable", "symlink", "directory", "missing", "unset"))
def test_restic_refuses_unsafe_password_files(monkeypatch, tmp_path, setup):
    if setup == "group-readable":
        monkeypatch.setenv("RESTIC_PASSWORD_FILE", str(password_file(tmp_path, 0o440)))
    elif setup == "symlink":
        link = tmp_path / "link"
        link.symlink_to(password_file(tmp_path, 0o400))
        monkeypatch.setenv("RESTIC_PASSWORD_FILE", str(link))
    elif setup == "directory":
        monkeypatch.setenv("RESTIC_PASSWORD_FILE", str(tmp_path))
    elif setup == "missing":
        monkeypatch.setenv("RESTIC_PASSWORD_FILE", str(tmp_path / "absent"))
    else:
        monkeypatch.delenv("RESTIC_PASSWORD_FILE", raising=False)
    monkeypatch.setattr(collector, "run", lambda *_args, **_kwargs: pytest.fail("restic must not run"))
    result = collector.restic_snapshot()
    assert result["snapshots"] == [] and result["error"]


def test_restic_refuses_a_password_file_owned_by_another_user(monkeypatch, tmp_path):
    monkeypatch.setenv("RESTIC_PASSWORD_FILE", str(password_file(tmp_path, 0o400)))
    monkeypatch.setattr(collector.os, "geteuid", lambda: os.getuid() + 1)
    monkeypatch.setattr(collector, "run", lambda *_args, **_kwargs: pytest.fail("restic must not run"))
    assert collector.restic_snapshot()["error"] == "RESTIC_PASSWORD_FILE must be root-owned mode 0400"


BACKUP_UUID = "9d872bab-a481-4fca-8ad8-8031d78c0dbc"


def test_disk_list_maps_roles_to_filesystem_uuids_only(monkeypatch):
    monkeypatch.setenv("STORAGE_TELEMETRY_DISKS", f"backup:{BACKUP_UUID} archive:/dev/sda Bad:{BACKUP_UUID}")
    assert collector.disk_list() == [("backup", BACKUP_UUID)]


@pytest.mark.parametrize(("output", "device"), (
    ("sdd\n", "/dev/sdd"),
    ("nvme0n1\n", "/dev/nvme0n1"),
    ("sdab\n", "/dev/sdab"),
))
def test_resolve_disk_accepts_exactly_one_whole_disk(monkeypatch, output, device):
    calls = []

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        return output, None

    monkeypatch.setattr(collector, "run", fake_run)
    assert collector.resolve_disk(BACKUP_UUID) == (device, None)
    assert calls == [["lsblk", "-no", "PKNAME", f"/dev/disk/by-uuid/{BACKUP_UUID}"]]


@pytest.mark.parametrize(("output", "error"), (
    ("\nsdd\n", None),   # UUID on a whole disk: lsblk also lists its children
    ("sdd\nsde\n", None),
    ("\n", None),        # whole-disk filesystem: no parent
    ("", None),
    ("dm-0\n", None),
    ("sdd1\n", None),
    ("nvme0n1p2\n", None),
    ("../sdd\n", None),
    (None, "command exited with status 32"),
))
def test_resolve_disk_never_guesses(monkeypatch, output, error):
    monkeypatch.setattr(collector, "run", lambda *_args, **_kwargs: (output, error))
    device, reason = collector.resolve_disk(BACKUP_UUID)
    assert device is None and reason


def smartctl_json(*, standby=False, crc=0, passed=True):
    if standby:
        return json.dumps({"smartctl": {"exit_status": 2, "messages": [
            {"string": "Device is in STANDBY mode, exit(2)", "severity": "information"}]}})
    return json.dumps({
        "smartctl": {"exit_status": 0},
        "smart_status": {"passed": passed},
        "temperature": {"current": 34},
        "ata_smart_attributes": {"table": [
            {"id": 5, "raw": {"value": 0}}, {"id": 199, "raw": {"value": crc}}, {"id": 9, "raw": {"value": 123}},
        ]},
    })


def fake_host(monkeypatch, smartctl_output, lsblk_output="sdd\n"):
    calls = []

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        if argv[0] == "lsblk":
            return lsblk_output, None
        assert argv[0] == "smartctl"
        return smartctl_output, None

    monkeypatch.setattr(collector, "run", fake_run)
    return calls


def test_smart_record_queries_the_resolved_disk_without_waking_it(monkeypatch):
    calls = fake_host(monkeypatch, smartctl_json(crc=4))
    record = collector.smart_record("backup", BACKUP_UUID, {}, now=NOW)
    assert calls[1] == ["smartctl", "-n", "standby", "-H", "-A", "-d", "sat", "--json=c", "/dev/sdd"]
    assert record == {"role": "backup", "device": "/dev/sdd", "state": "active", "smart_mode": "full", "type": "sat",
                      "passed": True, "checked_at": NOW.isoformat(),
                      "attributes": {"5": 0, "199": 4}, "udma_crc_error_count_rise": False, "temperature": 34,
                      "error": None}


def test_unresolved_disk_records_an_error_and_never_runs_smartctl(monkeypatch):
    calls = fake_host(monkeypatch, smartctl_json(), lsblk_output="\nsdd\n")
    record = collector.smart_record("backup", BACKUP_UUID, {"backup": 4})
    assert [argv[0] for argv in calls] == ["lsblk"]
    assert record["device"] is None
    assert record["error"] == "filesystem UUID did not resolve to exactly one whole disk"
    assert record["crc_baseline"] == 4


def test_standby_disk_is_recorded_without_error_and_keeps_the_crc_baseline(monkeypatch):
    fake_host(monkeypatch, smartctl_json(standby=True))
    record = collector.smart_record("backup", BACKUP_UUID, {"backup": 4}, now=NOW)
    assert record == {"role": "backup", "device": "/dev/sdd", "state": "standby", "passed": None,
                      "attributes": {}, "error": None, "crc_baseline": 4, "checked_at": NOW.isoformat()}


def test_crc_baseline_survives_standby_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(collector, "OUTPUT", tmp_path / "storage-telemetry.json")
    assert collector.previous_crc_counts() == {}

    def run_once(output):
        fake_host(monkeypatch, output)
        record = collector.smart_record("backup", BACKUP_UUID, collector.previous_crc_counts())
        collector.OUTPUT.write_text(json.dumps({"smart": [record]}), encoding="utf-8")
        return record

    assert run_once(smartctl_json(crc=4))["udma_crc_error_count_rise"] is False
    assert run_once(smartctl_json(standby=True))["crc_baseline"] == 4
    assert run_once(smartctl_json(standby=True))["crc_baseline"] == 4
    assert collector.previous_crc_counts() == {"backup": 4}
    assert run_once(smartctl_json(crc=4))["udma_crc_error_count_rise"] is False
    assert run_once(smartctl_json(crc=6))["udma_crc_error_count_rise"] is True


def test_previous_crc_counts_ignores_records_without_a_reading(monkeypatch, tmp_path):
    monkeypatch.setattr(collector, "OUTPUT", tmp_path / "storage-telemetry.json")
    collector.OUTPUT.write_text(json.dumps({"smart": [
        {"role": "backup", "attributes": {}, "error": "command could not be completed"},
        {"role": "archive", "attributes": {"199": 2}},
        {"role": "other", "attributes": {"199": True}},
        "not-a-record",
    ]}), encoding="utf-8")
    assert collector.previous_crc_counts() == {"archive": 2}
    collector.OUTPUT.write_text("not json", encoding="utf-8")
    assert collector.previous_crc_counts() == {}


ROOT_UUID = "9f3cd4b6-f34e-435e-9fcf-ed7861f7cf99"


def nvme_json(*, used=3, media_errors=0, temperature=41, passed=True):
    return json.dumps({
        "smartctl": {"exit_status": 0}, "smart_status": {"passed": passed},
        "nvme_smart_health_information_log": {
            "percentage_used": used, "media_errors": media_errors, "temperature": temperature,
            "available_spare": 100, "power_on_hours": 1234,
        },
    })


def test_root_nvme_is_resolved_by_uuid_and_queried_as_nvme(monkeypatch):
    calls = fake_host(monkeypatch, nvme_json(), lsblk_output="nvme0n1\n")
    record = collector.smart_record("root", ROOT_UUID, {}, now=NOW)
    assert calls == [
        ["lsblk", "-no", "PKNAME", f"/dev/disk/by-uuid/{ROOT_UUID}"],
        ["smartctl", "-n", "standby", "-H", "-A", "-d", "nvme", "--json=c", "/dev/nvme0n1"],
    ]
    assert record == {"role": "root", "device": "/dev/nvme0n1", "state": "active", "smart_mode": "full", "type": "nvme",
                      "passed": True, "checked_at": NOW.isoformat(),
                      "attributes": {}, "nvme": {"percentage_used": 3, "media_errors": 0, "temperature": 41},
                      "temperature": 41, "error": None}


def test_nvme_without_a_health_log_is_an_error(monkeypatch):
    fake_host(monkeypatch, json.dumps({"smart_status": {"passed": True}}), lsblk_output="nvme0n1\n")
    assert collector.smart_record("root", ROOT_UUID, {})["error"] == "smartctl returned invalid JSON"


def test_non_object_smartctl_json_is_an_error(monkeypatch):
    fake_host(monkeypatch, "[]")
    assert collector.smart_record("backup", BACKUP_UUID, {})["error"] == "smartctl returned invalid JSON"


DATA_UUID, B_UUID = "39b9324a-640e-4d64-9980-b1f1c9d5578b", "6A7F-D1A6"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def bridge(monkeypatch, sat_output, scsi_output=None, disk="sdg"):
    calls = []

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        if argv[0] == "lsblk":
            return f"{disk}\n", None
        if "-d" in argv and argv[argv.index("-d") + 1] == "scsi":
            return scsi_output, None if scsi_output is not None else "command could not be completed"
        return sat_output, None

    monkeypatch.setattr(collector, "run", fake_run)
    return calls


@pytest.mark.parametrize(("role", "uuid", "disk", "sat_fixture"), (
    ("data2tb", DATA_UUID, "sdg", "sdg-sat-read-device-identity-failed.json"),
    ("archive2tb-b", B_UUID, "sdh", "sdh-sat-mandatory-command-failed.json"),
))
def test_bridge_without_sat_falls_back_to_scsi_health_only(monkeypatch, role, uuid, disk, sat_fixture):
    calls = bridge(monkeypatch, fixture(sat_fixture), fixture("sdg-scsi-health-ok.json"), disk=disk)
    record = collector.smart_record(role, uuid, {}, now=NOW)
    assert calls[1:] == [
        ["smartctl", "-n", "standby", "-H", "-A", "-d", "sat", "--json=c", f"/dev/{disk}"],
        ["smartctl", "-H", "-d", "scsi", "--json=c", f"/dev/{disk}"],
    ]
    assert not [argv for argv in calls if "-T" in argv or "permissive" in argv]
    assert record == {"role": role, "device": f"/dev/{disk}", "state": None, "smart_mode": "scsi_health_only",
                      "power_state": "unknown", "type": "scsi", "passed": True, "attributes": {},
                      "checked_at": NOW.isoformat(), "error": None}


def test_scsi_health_failure_is_recorded_as_failed(monkeypatch):
    bridge(monkeypatch, fixture("sdh-sat-mandatory-command-failed.json"), fixture("sdh-scsi-health-failed.json"), disk="sdh")
    record = collector.smart_record("archive2tb-b", B_UUID, {}, now=NOW)
    assert (record["smart_mode"], record["passed"], record["error"]) == ("scsi_health_only", False, None)


@pytest.mark.parametrize("scsi_output", (None, "not json", '{"smartctl": {"exit_status": 2}}'))
def test_scsi_fallback_without_a_health_status_is_an_error(monkeypatch, scsi_output):
    bridge(monkeypatch, fixture("sdg-sat-read-device-identity-failed.json"), scsi_output)
    record = collector.smart_record("data2tb", DATA_UUID, {}, now=NOW)
    assert record["smart_mode"] == "scsi_health_only" and record["passed"] is None and record["error"]


def test_rejected_power_check_records_unknown_not_standby(monkeypatch):
    bridge(monkeypatch, fixture("sat-check-power-mode-rejected.json"))
    record = collector.smart_record("data2tb", DATA_UUID, {}, now=NOW)
    assert (record["power_state"], record["state"], record["smart_mode"]) == ("unknown", None, "full")
    assert record["attributes"] == {"5": 0, "197": 0, "198": 0, "199": 2} and record["passed"] is True


@pytest.mark.parametrize("message", (
    "CHECK POWER MODE: incomplete response, ATA output registers missing",
    "CHECK POWER MODE returned unknown value 0x80, ignoring -n option",
    "scsi error: Illegal Request",
    "Sense key 05/24: unsupported field in scsi command",
))
def test_every_power_check_rejection_is_unknown(monkeypatch, message):
    raw = json.loads(fixture("sat-check-power-mode-rejected.json"))
    raw["smartctl"]["messages"] = [{"string": message, "severity": "information"},
                                   {"string": "Device is in STANDBY mode, exit(2)", "severity": "information"}]
    bridge(monkeypatch, json.dumps(raw))
    record = collector.smart_record("data2tb", DATA_UUID, {}, now=NOW)
    assert record["power_state"] == "unknown" and record["state"] != "standby"


def checked(hours_ago: float, **extra):
    return {"role": "data2tb", "device": "/dev/sdg", "state": None, "smart_mode": "scsi_health_only",
            "power_state": "unknown", "type": "scsi", "passed": True, "attributes": {},
            "checked_at": (NOW - timedelta(hours=hours_ago)).isoformat(), "error": None, **extra}


@pytest.mark.parametrize("hours_ago", (0, 1, 5.99))
def test_unknown_power_disk_is_not_queried_again_within_six_hours(monkeypatch, hours_ago):
    calls = bridge(monkeypatch, fixture("sdg-sat-read-device-identity-failed.json"), fixture("sdg-scsi-health-ok.json"), disk="sdi")
    last = checked(hours_ago)
    record = collector.smart_record("data2tb", DATA_UUID, {}, last, now=NOW)
    assert [argv[0] for argv in calls] == ["lsblk"]          # resolving the UUID does not wake the disk
    assert record == {**last, "device": "/dev/sdi", "reused": True}


@pytest.mark.parametrize("last", (
    checked(6),                                   # due
    checked(30),
    checked(-1),                                  # checked_at in the future: don't trust it
    checked(1, checked_at="not a time"),
    checked(1, checked_at="2026-10-22T05:00:00"),  # no timezone
    checked(1, power_state=None),                 # power state is readable: no throttle
    None,
))
def test_unknown_power_disk_is_queried_when_due(monkeypatch, last):
    calls = bridge(monkeypatch, fixture("sdg-sat-read-device-identity-failed.json"), fixture("sdg-scsi-health-ok.json"))
    record = collector.smart_record("data2tb", DATA_UUID, {}, last, now=NOW)
    assert [argv[0] for argv in calls] == ["lsblk", "smartctl", "smartctl"]
    assert record["checked_at"] == NOW.isoformat() and "reused" not in record


def test_hourly_runs_query_an_unknown_power_disk_once_per_six_hours(monkeypatch, tmp_path):
    monkeypatch.setattr(collector, "OUTPUT", tmp_path / "storage-telemetry.json")
    calls = bridge(monkeypatch, fixture("sdg-sat-read-device-identity-failed.json"), fixture("sdg-scsi-health-ok.json"))
    for hour in range(13):
        last = collector.previous_smart_records().get("data2tb")
        record = collector.smart_record("data2tb", DATA_UUID, {}, last, now=NOW + timedelta(hours=hour))
        collector.OUTPUT.write_text(json.dumps({"smart": [record]}), encoding="utf-8")
        assert record["passed"] is True and record["power_state"] == "unknown"
    queries = [argv for argv in calls if argv[0] == "smartctl" and "scsi" in argv]
    assert len(queries) == 3                     # hours 0, 6 and 12


def test_previous_smart_records_reads_the_last_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(collector, "OUTPUT", tmp_path / "storage-telemetry.json")
    assert collector.previous_smart_records() == {}
    collector.OUTPUT.write_text(json.dumps({"smart": [checked(1), "junk", {"no": "role"}]}), encoding="utf-8")
    assert list(collector.previous_smart_records()) == ["data2tb"]
    collector.OUTPUT.write_text(json.dumps({"smart": "junk"}), encoding="utf-8")
    assert collector.previous_smart_records() == {}


SLEEP_MESSAGE = "Device is in SLEEP mode, exit(2)"


def test_sleep_mode_fixture_carries_the_exact_message():
    raw = json.loads(fixture("sdg-sat-sleep-mode-false.json"))
    assert collector.smartctl_messages(raw) == [SLEEP_MESSAGE]
    assert raw["smartctl"]["exit_status"] == 2


def test_sleep_mode_is_standby_for_a_disk_with_a_working_power_check(monkeypatch):
    monkeypatch.delenv("STORAGE_TELEMETRY_NO_POWER_CHECK", raising=False)
    calls = bridge(monkeypatch, fixture("sdg-sat-sleep-mode-false.json"), fixture("sdg-scsi-health-ok.json"), disk="sdd")
    record = collector.smart_record("backup", BACKUP_UUID, {"backup": 4}, now=NOW)
    assert (record["state"], record["error"], record.get("power_state")) == ("standby", None, None)
    assert record["crc_baseline"] == 4
    assert [argv for argv in calls if argv[0] == "smartctl"] == [
        ["smartctl", "-n", "standby", "-H", "-A", "-d", "sat", "--json=c", "/dev/sdd"]]   # no SCSI fallback


def test_without_the_opt_out_a_false_sleep_answer_hides_the_disk(monkeypatch):
    # The bug this opt-out fixes: the bridge always answers SLEEP, so the fallback never runs.
    monkeypatch.delenv("STORAGE_TELEMETRY_NO_POWER_CHECK", raising=False)
    calls = bridge(monkeypatch, fixture("sdg-sat-sleep-mode-false.json"), fixture("sdg-scsi-health-ok.json"))
    record = collector.smart_record("data2tb", DATA_UUID, {}, now=NOW)
    assert record["state"] == "standby" and record["passed"] is None
    assert not [argv for argv in calls if "scsi" in argv]


@pytest.mark.parametrize(("role", "uuid", "disk", "sat_fixture"), (
    ("data2tb", DATA_UUID, "sdg", "sdg-sat-read-device-identity-failed.json"),
    ("archive2tb-b", B_UUID, "sdh", "sdh-sat-mandatory-command-failed.json"),
))
def test_opted_out_roles_skip_the_power_check_and_fall_back_to_scsi(monkeypatch, role, uuid, disk, sat_fixture):
    monkeypatch.setenv("STORAGE_TELEMETRY_NO_POWER_CHECK", "data2tb archive2tb-b")
    calls = bridge(monkeypatch, fixture(sat_fixture), fixture("sdg-scsi-health-ok.json"), disk=disk)
    record = collector.smart_record(role, uuid, {}, now=NOW)
    assert [argv for argv in calls if argv[0] == "smartctl"] == [
        ["smartctl", "-H", "-A", "-d", "sat", "--json=c", f"/dev/{disk}"],
        ["smartctl", "-H", "-d", "scsi", "--json=c", f"/dev/{disk}"],
    ]
    assert not [argv for argv in calls if "-n" in argv or "standby" in argv or "-T" in argv]
    assert (record["smart_mode"], record["power_state"], record["passed"], record["error"]) == (
        "scsi_health_only", "unknown", True, None)


def test_opted_out_role_ignores_a_sleep_answer(monkeypatch):
    monkeypatch.setenv("STORAGE_TELEMETRY_NO_POWER_CHECK", "data2tb")
    raw = json.loads(fixture("sat-check-power-mode-rejected.json"))
    raw["smartctl"]["messages"] = [{"string": SLEEP_MESSAGE, "severity": "information"}]
    bridge(monkeypatch, json.dumps(raw))
    record = collector.smart_record("data2tb", DATA_UUID, {}, now=NOW)
    assert (record["state"], record["power_state"], record["smart_mode"], record["passed"]) == (None, "unknown", "full", True)
    assert record["attributes"] == {"5": 0, "197": 0, "198": 0, "199": 2}


def test_opted_out_role_that_answers_sat_records_full_smart_with_unknown_power(monkeypatch):
    monkeypatch.setenv("STORAGE_TELEMETRY_NO_POWER_CHECK", "data2tb")
    raw = json.loads(fixture("sat-check-power-mode-rejected.json"))
    raw["smartctl"]["messages"] = []
    bridge(monkeypatch, json.dumps(raw))
    record = collector.smart_record("data2tb", DATA_UUID, {}, now=NOW)
    assert (record["state"], record["power_state"], record["smart_mode"]) == (None, "unknown", "full")


def test_opted_out_role_is_checked_at_most_every_six_hours(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_TELEMETRY_NO_POWER_CHECK", "data2tb archive2tb-b")
    monkeypatch.setattr(collector, "OUTPUT", tmp_path / "storage-telemetry.json")
    calls = bridge(monkeypatch, fixture("sdg-sat-read-device-identity-failed.json"), fixture("sdg-scsi-health-ok.json"))
    for hour in range(13):
        last = collector.previous_smart_records().get("data2tb")
        record = collector.smart_record("data2tb", DATA_UUID, {}, last, now=NOW + timedelta(hours=hour))
        collector.OUTPUT.write_text(json.dumps({"smart": [record]}), encoding="utf-8")
        assert record["power_state"] == "unknown" and record["passed"] is True
    smartctl = [argv for argv in calls if argv[0] == "smartctl"]
    assert len([argv for argv in smartctl if "sat" in argv]) == 3        # hours 0, 6 and 12
    assert not [argv for argv in smartctl if "-n" in argv]


def test_opted_out_roles_ignore_malformed_entries(monkeypatch):
    monkeypatch.setenv("STORAGE_TELEMETRY_NO_POWER_CHECK", "data2tb Bad ../x archive2tb-b")
    assert collector.power_check_disabled_roles() == {"data2tb", "archive2tb-b"}
    monkeypatch.delenv("STORAGE_TELEMETRY_NO_POWER_CHECK")
    assert collector.power_check_disabled_roles() == set()
