from __future__ import annotations

from types import SimpleNamespace

from scripts import storage_metadata_collector as collector


def configure_fake_host(monkeypatch, *, omit=(), backup_fs="ext4", wrong_backup_identity=False, backup_root="/"):
    fstab_lines = ["UUID=root / ext4 defaults 0 1"]
    source_ids = {"UUID=root": "8:0", "UUID=primary": "8:1", "UUID=backup": "8:2",
                  "UUID=aw": "8:3", "UUID=a": "8:4", "UUID=b": "8:5"}
    role_sources = {"compute": "UUID=root", "primary": "UUID=primary", "backup": "UUID=backup",
                    "archive-writable": "UUID=aw", "archive-member-a": "UUID=a", "archive-member-b": "UUID=b"}
    for role, source in role_sources.items():
        if role == "backup":
            fs = backup_fs
        elif role == "archive-member-b":
            fs = "exfat"
        else:
            fs = "ext4"
        fstab_lines.append(f"{source} {collector.MOUNTS[role]} {fs} defaults 0 2")
    branches = ":".join(f"{collector.MOUNTS[role]}={'RW' if role == 'archive-writable' else 'RO'}" for role in collector.BRANCHES)
    fstab_lines.append(f"{branches} {collector.MOUNTS['archive-pool']} fuse.mergerfs rw,category.create=ff,minfreespace=10G,x-systemd.requires-mounts-for=/mnt/a,x-systemd.requires-mounts-for=/mnt/b 0 0")
    fstab = "\n".join(fstab_lines) + "\n"
    mount_lines = []
    for index, (role, path) in enumerate(collector.MOUNTS.items()):
        if role in omit:
            continue
        fs = "fuse.mergerfs" if role == "archive-pool" else backup_fs if role == "backup" else "exfat" if role == "archive-member-b" else "ext4"
        mm = "0:99" if role == "archive-pool" else source_ids[role_sources[role]]
        if role == "backup" and wrong_backup_identity:
            mm = "8:99"
        root = backup_root if role == "backup" else "/"
        mount_lines.append(f"{100 + index} 25 {mm} {root} {path} rw - {fs} {role_sources.get(role, 'mergerfs')} rw")
    monkeypatch.setattr(collector, "MOUNTINFO", type("P", (), {"open": lambda *_args, **_kw: __import__("io").BytesIO("\n".join(mount_lines).encode())})())
    monkeypatch.setattr(collector, "FSTAB", type("P", (), {"open": lambda *_args, **_kw: __import__("io").BytesIO(fstab.encode())})())
    monkeypatch.setattr(collector, "block_device_number", lambda source: source_ids.get(source))
    devices = {path: "0:99" if role == "archive-pool" else source_ids[role_sources[role]] for role, path in collector.MOUNTS.items()}
    monkeypatch.setattr(collector, "mount_device_number", lambda path: devices[path])
    monkeypatch.setattr(collector.os, "getxattr", lambda *_args: branches.encode())
    monkeypatch.setattr(collector.os, "statvfs", lambda _path: SimpleNamespace(f_blocks=1000, f_frsize=1, f_bfree=400, f_bavail=300))


def test_host_collector_reports_fixed_mount_capacities_and_pool_once(monkeypatch):
    configure_fake_host(monkeypatch)
    result = collector.collect()
    assert result["collector_status"] == "AVAILABLE"
    assert result["metrics"]["primary"]["total_bytes"] == 1000
    assert result["metrics"]["archive-pool"]["total_bytes"] == 1000
    assert sum(result["metrics"][role]["total_bytes"] for role in collector.BRANCHES) == 3000
    assert result["archive_complete"] is True
    assert result["archive_policy"] == {
        "create_policy": "ff", "min_free_bytes": 10 * 1024**3,
        "min_free_policy_status": "CONFIGURED", "dependency_count": 2,
    }


def test_host_collector_rejects_wrong_device_and_filesystem_identity(monkeypatch):
    configure_fake_host(monkeypatch, wrong_backup_identity=True)
    result = collector.collect()
    assert result["metrics"]["backup"]["status"] == "INVALID"
    assert result["metrics"]["backup"]["total_bytes"] is None
    configure_fake_host(monkeypatch, backup_fs="xfs")
    result = collector.collect()
    assert result["metrics"]["backup"]["status"] == "INVALID"
    configure_fake_host(monkeypatch, backup_root="/subdirectory")
    result = collector.collect()
    assert result["metrics"]["backup"]["status"] == "INVALID"


def test_host_collector_statvfs_permission_failure_withholds_capacity(monkeypatch):
    configure_fake_host(monkeypatch)
    original = collector.os.statvfs
    monkeypatch.setattr(collector.os, "statvfs", lambda path: (_ for _ in ()).throw(PermissionError()) if path == collector.MOUNTS["backup"] else original(path))
    result = collector.collect()
    assert result["metrics"]["backup"]["status"] == "INVALID"
    assert result["metrics"]["backup"]["total_bytes"] is None


def test_disconnected_archive_branch_withholds_pool_capacity(monkeypatch):
    configure_fake_host(monkeypatch, omit={"archive-member-b"})
    result = collector.collect()
    assert result["metrics"]["archive-member-b"]["status"] == "MISSING"
    assert result["archive_complete"] is False
    assert result["metrics"]["archive-pool"]["total_bytes"] is None


def test_runtime_archive_branches_must_match_configuration(monkeypatch):
    configure_fake_host(monkeypatch)
    monkeypatch.setattr(collector.os, "getxattr", lambda *_args: b"/other=RW")
    assert collector.collect()["metrics"]["archive-pool"]["status"] == "INVALID"
    monkeypatch.setattr(collector.os, "getxattr", lambda *_args: (_ for _ in ()).throw(PermissionError()))
    assert collector.collect()["archive_complete"] is False


def test_namespace_device_mismatch_withholds_capacity(monkeypatch):
    configure_fake_host(monkeypatch)
    monkeypatch.setattr(collector, "mount_device_number", lambda _path: "0:999")
    assert collector.collect()["collector_status"] == "UNAVAILABLE"
