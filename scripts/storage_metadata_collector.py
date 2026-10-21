#!/usr/bin/env python3
"""DGX host sampler: read fixed mount metadata and statvfs counters only.

This program never walks a storage directory or opens a stored file. Run it as
root from a systemd timer with a root-only Ed25519 private key. Its sole output
is the atomically replaced signed JSON snapshot under /run.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

MOUNTINFO = Path("/proc/self/mountinfo")
FSTAB = Path("/etc/fstab")
KEY = Path("/etc/omnibioai/storage-telemetry-ed25519.pem")
OUTPUT = Path("/run/omnibioai/storage-telemetry/snapshot.json")
MAX_INPUT = 2 * 1024 * 1024
MOUNTS = {
    "compute": "/",
    "primary": "/mnt/wdpro26tb",
    "backup": "/mnt/omnibioai-backup20tb",
    "archive-writable": "/mnt/omnibioai-archive22tb",
    "archive-member-a": "/media/manish/omnibioai-data",
    "archive-member-b": "/mnt/omnibioai-archive2tb-b",
    "archive-pool": "/mnt/omnibioai-archive",
}
BRANCHES = ("archive-writable", "archive-member-a", "archive-member-b")
EXPECTED_FS = {
    "compute": None, "primary": "ext4", "backup": "ext4",
    "archive-writable": "ext4", "archive-member-a": "ext4",
    "archive-member-b": "exfat", "archive-pool": "fuse.mergerfs",
}
MIN_FREE_MULTIPLIERS = {"k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}


def unescape(value: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), value)


def read_fixed(path: Path) -> str:
    with path.open("rb") as stream:
        data = stream.read(MAX_INPUT + 1)
    if len(data) > MAX_INPUT:
        raise ValueError("metadata input exceeds limit")
    return data.decode("utf-8")


def parse_mountinfo(text: str) -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        fields = line.split()
        try:
            dash = fields.index("-")
            target = unescape(fields[4])
            found[target] = {"major_minor": fields[2], "root": unescape(fields[3]), "mode": fields[5],
                             "filesystem": fields[dash + 1], "source": unescape(fields[dash + 2])}
        except (ValueError, IndexError):
            continue
    return found


def parse_fstab(text: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        fields = line.split("#", 1)[0].split()
        if len(fields) >= 4:
            result[unescape(fields[1])] = {"source": unescape(fields[0]), "filesystem": fields[2], "options": fields[3]}
    return result


def block_device_number(source: str) -> str | None:
    if source.startswith("UUID="):
        path = Path("/dev/disk/by-uuid") / source[5:]
    elif source.startswith("LABEL="):
        path = Path("/dev/disk/by-label") / source[6:]
    else:
        path = Path(source)
    try:
        info = path.stat()
        if not stat.S_ISBLK(info.st_mode):
            return None
        return f"{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}"
    except OSError:
        return None


def mount_device_number(target: str) -> str:
    device = os.stat(target).st_dev
    return f"{os.major(device)}:{os.minor(device)}"


def runtime_pool_matches(source: str) -> bool:
    """Read mergerfs's synthetic control inode metadata, never stored files."""
    try:
        actual = os.getxattr(MOUNTS["archive-pool"] + "/.mergerfs", "user.mergerfs.branches").decode()
        return actual == source
    except (OSError, UnicodeError):
        return False


def mounted_metric(role: str, mounts: dict[str, dict[str, str]], fstab: dict[str, dict[str, str]]) -> dict[str, object]:
    target = MOUNTS[role]
    mount, configured = mounts.get(target), fstab.get(target)
    base = {"status": "MISSING", "filesystem": None, "device_fingerprint": None,
            "mount_mode": "UNKNOWN", "expected_mode": "UNKNOWN", "total_bytes": None,
            "used_bytes": None, "available_bytes": None}
    if mount is None:
        return base
    if configured is None:
        base["status"] = "INVALID"
        return base
    if mount["root"] != "/":
        base["status"] = "INVALID"
        return base
    expected_fs = EXPECTED_FS[role] or configured["filesystem"]
    if mount["filesystem"] != expected_fs or configured["filesystem"] != expected_fs:
        base["status"] = "INVALID"
        return base
    options = mount["mode"].split(",")
    if not {"ro", "rw"}.intersection(options):
        base["status"] = "INVALID"
        return base
    if expected_fs != "fuse.mergerfs" and block_device_number(configured["source"]) != mount["major_minor"]:
        base["status"] = "INVALID"
        return base
    try:
        if mount_device_number(target) != mount["major_minor"]:
            raise OSError("mount identity changed")
        capacity = os.statvfs(target)
        if mount_device_number(target) != mount["major_minor"]:
            raise OSError("mount identity changed")
    except OSError:
        base["status"] = "INVALID"
        return base
    total = capacity.f_blocks * capacity.f_frsize
    used = max(0, total - capacity.f_bfree * capacity.f_frsize)
    available = capacity.f_bavail * capacity.f_frsize
    if total <= 0 or used + available > total:
        base["status"] = "INVALID"
        return base
    fingerprint = hashlib.sha256((mount["major_minor"] + "\0" + mount["source"] + "\0" + expected_fs).encode()).hexdigest()
    base.update(status="AVAILABLE", filesystem=expected_fs, device_fingerprint=fingerprint,
                mount_mode="READ_ONLY" if "ro" in options else "READ_WRITE",
                total_bytes=total, used_bytes=used, available_bytes=available)
    return base


def collect() -> dict[str, object]:
    mounts, fstab = parse_mountinfo(read_fixed(MOUNTINFO)), parse_fstab(read_fixed(FSTAB))
    metrics = {role: mounted_metric(role, mounts, fstab) for role in MOUNTS}
    pool_source = fstab.get(MOUNTS["archive-pool"], {}).get("source", "")
    pool_options = fstab.get(MOUNTS["archive-pool"], {}).get("options", "").split(",")
    configured_branches = {item.rpartition("=")[0] for item in pool_source.split(":") if item.rpartition("=")[1] and item.rpartition("=")[2] in {"RW", "RO"}}
    branch_modes = {}
    for item in pool_source.split(":"):
        branch, separator, mode = item.rpartition("=")
        if separator and mode in {"RW", "RO"}:
            branch_modes[branch] = "READ_WRITE" if mode == "RW" else "READ_ONLY"
    for role in BRANCHES:
        metrics[role]["expected_mode"] = branch_modes.get(MOUNTS[role], "UNKNOWN")
    expected_branches = {MOUNTS[role] for role in BRANCHES}
    branch_complete = configured_branches == expected_branches and all(metrics[role]["status"] == "AVAILABLE" for role in BRANCHES)
    pool_complete = branch_complete and metrics["archive-pool"]["status"] == "AVAILABLE" and runtime_pool_matches(pool_source)
    if not pool_complete:
        metrics["archive-pool"] = {"status": "INVALID", "filesystem": None, "device_fingerprint": None,
                                   "mount_mode": "UNKNOWN", "expected_mode": "UNKNOWN", "total_bytes": None,
                                   "used_bytes": None, "available_bytes": None}
    statuses = [metric["status"] for metric in metrics.values()]
    state = "AVAILABLE" if all(item == "AVAILABLE" for item in statuses) else "PARTIAL" if any(item == "AVAILABLE" for item in statuses) else "UNAVAILABLE"
    create_policy = next((item.split("=", 1)[1] for item in pool_options
                          if item.startswith("category.create=") and re.fullmatch(r"[A-Za-z0-9_-]{1,32}", item.split("=", 1)[1])), None)
    min_free = None
    min_free_status = "NOT_CONFIGURED"
    for option in pool_options:
        if not option.startswith("minfreespace="):
            continue
        min_free_status = "UNKNOWN"
        value = option.split("=", 1)[1].strip()
        suffix = value[-1:].lower()
        if suffix in MIN_FREE_MULTIPLIERS:
            value = value[:-1]
            multiplier = MIN_FREE_MULTIPLIERS[suffix]
        else:
            multiplier = 1
        if value.isdigit():
            parsed = int(value) * multiplier
            if parsed <= 2**63 - 1:
                min_free, min_free_status = parsed, "CONFIGURED"
        break
    dependency_count = sum(option.startswith("x-systemd.requires-mounts-for=") for option in pool_options)
    return {"schema_version": 1, "observed_at": datetime.now(timezone.utc).isoformat(),
            "collector_status": state, "metrics": metrics, "archive_complete": pool_complete,
            "archive_policy": {"create_policy": create_policy, "min_free_bytes": min_free,
                               "min_free_policy_status": min_free_status, "dependency_count": dependency_count}}


def publish_snapshot(payload: dict[str, object], private_key: Ed25519PrivateKey, output: Path = OUTPUT) -> None:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    envelope = {"payload": payload, "signature": base64.b64encode(private_key.sign(canonical)).decode("ascii")}
    output.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".storage-snapshot-", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o444)
            stream.write(json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
        directory_fd = os.open(output.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main() -> None:
    key_fd = os.open(KEY, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        key_info = os.fstat(key_fd)
        if (not stat.S_ISREG(key_info.st_mode) or key_info.st_uid != 0
                or key_info.st_nlink != 1 or key_info.st_mode & 0o077 or key_info.st_size > 4096):
            raise PermissionError("signing key permissions are invalid")
        key_data = os.read(key_fd, 4097)
    finally:
        os.close(key_fd)
    private_key = serialization.load_pem_private_key(key_data, password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("signing key algorithm is invalid")
    publish_snapshot(collect(), private_key)


if __name__ == "__main__":
    main()
