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
