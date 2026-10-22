from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[2] / "ops/storage-telemetry/collect-storage-telemetry.py"
SPEC = importlib.util.spec_from_file_location("storage_host_collector", SCRIPT)
assert SPEC and SPEC.loader
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


def test_mount_check_matches_configured_uuid_with_findmnt(monkeypatch):
    monkeypatch.setenv("STORAGE_TELEMETRY_TARGETS", "backup|/mnt/backup|12345678-aaaa")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return "12345678-aaaa\n", None

    monkeypatch.setattr(collector, "run", fake_run)
    assert collector.mount_records() == {"backup": {"mounted": True, "uuid": "12345678-aaaa"}}
    assert calls == [["findmnt", "-n", "-o", "UUID", "/mnt/backup"]]

    monkeypatch.setattr(collector, "run", lambda *_args, **_kwargs: ("other-uuid\n", None))
    assert collector.mount_records() == {"backup": {"mounted": False, "uuid": "other-uuid"}}

    # findmnt exits 1 when the path is not a mountpoint.
    monkeypatch.setattr(collector, "run", lambda *_args, **_kwargs: (None, "command exited with status 1"))
    assert collector.mount_records() == {"backup": {"mounted": False, "uuid": None}}


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


def test_restic_uses_only_bounded_read_only_commands(monkeypatch, tmp_path):
    monkeypatch.setenv("RESTIC_PASSWORD_FILE", str(password_file(tmp_path, 0o400)))
    monkeypatch.setenv("RESTIC_REPOSITORY", "/backup/restic")
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-reach-restic")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs["timeout"]))
        assert "UNRELATED_SECRET" not in kwargs["env"]
        return ("[]" if argv[1] == "snapshots" else '{"total_size": 1}', None)

    monkeypatch.setattr(collector, "run", fake_run)
    result = collector.restic_snapshot()
    assert result == {"snapshots": [], "stats": {"total_size": 1}, "error": None}
    assert calls == [
        (["restic", "snapshots", "--json", "--no-lock"], 600),
        (["restic", "stats", "latest", "--json", "--no-lock"], 600),
    ]


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
    record = collector.smart_record("backup", BACKUP_UUID, {})
    assert calls[1] == ["smartctl", "-n", "standby", "-H", "-A", "-d", "sat", "--json=c", "/dev/sdd"]
    assert record == {"role": "backup", "device": "/dev/sdd", "state": "active", "passed": True,
                      "attributes": {"5": 0, "199": 4}, "udma_crc_error_count_rise": False, "error": None}


def test_unresolved_disk_records_an_error_and_never_runs_smartctl(monkeypatch):
    calls = fake_host(monkeypatch, smartctl_json(), lsblk_output="\nsdd\n")
    record = collector.smart_record("backup", BACKUP_UUID, {"backup": 4})
    assert [argv[0] for argv in calls] == ["lsblk"]
    assert record["device"] is None
    assert record["error"] == "filesystem UUID did not resolve to exactly one whole disk"
    assert record["crc_baseline"] == 4


def test_standby_disk_is_recorded_without_error_and_keeps_the_crc_baseline(monkeypatch):
    fake_host(monkeypatch, smartctl_json(standby=True))
    record = collector.smart_record("backup", BACKUP_UUID, {"backup": 4})
    assert record == {"role": "backup", "device": "/dev/sdd", "state": "standby", "passed": None,
                      "attributes": {}, "error": None, "crc_baseline": 4}


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
