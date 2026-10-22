#!/usr/bin/env python3
"""Collect bounded host storage health metadata into one atomic JSON snapshot."""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUTPUT = Path("/var/lib/omnibioai/storage-telemetry.json")
MAX_OUTPUT = 2 * 1024 * 1024
ERROR_PATTERNS = {
    "io_errors": re.compile(r"I/O error", re.IGNORECASE),
    "resets": re.compile(r"reset", re.IGNORECASE),
    "ext4_errors": re.compile(r"EXT4-fs error", re.IGNORECASE),
}
# Standard filesystem UUIDs, or the short FAT/exFAT volume serial (6A7F-D1A6).
UUID = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}|[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}")
HOST_PATH = re.compile(r"/[A-Za-z0-9._/-]*")
MERGERFS_CONTROL = ".mergerfs"
ROLE = re.compile(r"[a-z][a-z0-9_-]{0,31}")
WHOLE_DISK = re.compile(r"sd[a-z]{1,2}|nvme\d+n\d+")
STANDBY_MESSAGE = re.compile(r"Device is in (STANDBY|SLEEP)", re.IGNORECASE)
# smartctl 7.4 messages when a USB bridge cannot pass ATA commands through SAT.
SAT_UNSUPPORTED = re.compile(r"Read Device Identity failed|A mandatory SMART command failed")
# ...and when it rejects the power-mode check (ILLEGAL REQUEST, sense 05/24).
POWER_CHECK_REJECTED = re.compile(
    r"CHECK POWER MODE(?: not implemented|: incomplete response| returned unknown value)"
    r"|Illegal Request|unsupported field in scsi command|\b05/24\b", re.IGNORECASE)
# A disk whose power state can't be read could be woken by any query, so its
# health is checked at most this often; the last result is kept in between.
UNKNOWN_POWER_INTERVAL = timedelta(hours=6)
DEVICE_NAME = re.compile(r"\b(sd[a-z]{1,2}\d*|nvme\d+(?:n\d+(?:p\d+)?)?|dm-\d+)\b")
MAX_KERNEL_DEVICES = 16


def run(argv: list[str], env: dict[str, str] | None = None, timeout: int = 120,
        accepted_statuses: set[int] | None = None) -> tuple[str | None, str | None]:
    try:
        result = subprocess.run(
            argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            env=env, timeout=timeout, check=False,
        )
        if result.returncode not in (accepted_statuses or {0}):
            return None, f"command exited with status {result.returncode}"
        if len(result.stdout.encode()) > MAX_OUTPUT:
            return None, "command output exceeded the size limit"
        return result.stdout, None
    except (OSError, subprocess.TimeoutExpired):
        return None, "command could not be completed"


def previous_smart_records() -> dict[str, dict[str, object]]:
    """The last snapshot's SMART record per role."""
    try:
        prior = json.loads(OUTPUT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    items = prior.get("smart") if isinstance(prior, dict) else None
    return {str(item["role"]): item for item in items or [] if isinstance(item, dict) and item.get("role")} \
        if isinstance(items, list) else {}


def previous_crc_counts(records: dict[str, dict[str, object]] | None = None) -> dict[str, int]:
    """Last known attribute 199 per role; roles without a reading have no baseline."""
    baselines = {}
    for role, item in (previous_smart_records() if records is None else records).items():
        attributes = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
        value = attributes.get("199", item.get("crc_baseline"))
        if isinstance(value, int) and not isinstance(value, bool):
            baselines[role] = value
    return baselines


def recently_checked_unknown_power(last: dict[str, object] | None, now: datetime) -> bool:
    if not last or last.get("power_state") != "unknown" or not isinstance(last.get("checked_at"), str):
        return False
    try:
        checked = datetime.fromisoformat(str(last["checked_at"]))
    except ValueError:
        return False
    if checked.tzinfo is None:
        return False
    return timedelta(0) <= now - checked < UNKNOWN_POWER_INTERVAL


def smartctl_messages(raw: object) -> list[str]:
    messages = raw.get("smartctl", {}).get("messages") if isinstance(raw, dict) and isinstance(raw.get("smartctl"), dict) else None
    return [str(item.get("string", "")) for item in messages if isinstance(item, dict)] if isinstance(messages, list) else []


def scsi_health(record: dict[str, object], device: str) -> dict[str, object]:
    """Health status only, for a bridge that rejects SAT pass-through. Never -T permissive."""
    text, error = run(["smartctl", "-H", "-d", "scsi", "--json=c", device], timeout=45,
                      accepted_statuses=set(range(256)))
    record.update({"smart_mode": "scsi_health_only", "power_state": "unknown", "state": None,
                   "type": "scsi", "attributes": {}, "error": error})
    if text is None:
        record["error"] = error or "smartctl -d scsi returned no output"
        return record
    try:
        smart_status = json.loads(text).get("smart_status")
    except (AttributeError, ValueError):
        smart_status = None
    if isinstance(smart_status, dict) and isinstance(smart_status.get("passed"), bool):
        record.update({"passed": smart_status["passed"], "error": None})
    else:
        record["error"] = "smartctl -d scsi returned no health status"
    return record


def resolve_disk(uuid: str) -> tuple[str | None, str | None]:
    """Map a filesystem UUID to its whole disk; never guess a device name."""
    text, error = run(["lsblk", "-no", "PKNAME", f"/dev/disk/by-uuid/{uuid}"], timeout=15)
    if error:
        return None, "filesystem UUID did not resolve to a block device"
    lines = (text or "").splitlines()
    if len(lines) != 1 or not WHOLE_DISK.fullmatch(lines[0].strip()):
        return None, "filesystem UUID did not resolve to exactly one whole disk"
    return f"/dev/{lines[0].strip()}", None


def power_check_disabled_roles() -> set[str]:
    """Roles whose bridge misreports power mode, so -n standby must not be used.

    The Seagate bridges here answer "Device is in SLEEP mode, exit(2)" even
    right after a read woke the disk, which would hide them forever.
    """
    return {role for role in os.environ.get("STORAGE_TELEMETRY_NO_POWER_CHECK", "").split() if ROLE.fullmatch(role)}


def smart_record(role: str, uuid: str, previous: dict[str, int], last: dict[str, object] | None = None,
                 now: datetime | None = None) -> dict[str, object]:
    moment = now or datetime.now(timezone.utc)
    device, error = resolve_disk(uuid)
    record: dict[str, object] = {"role": role, "device": device, "state": None, "passed": None,
                                 "attributes": {}, "error": error}
    # Carried forward until a fresh attribute 199 reading replaces it.
    if role in previous:
        record["crc_baseline"] = previous[role]
    if device is None:
        return record
    if recently_checked_unknown_power(last, moment):
        kept = {**(last or {}), "device": device, "reused": True}
        return kept
    record["checked_at"] = moment.isoformat()
    # -n standby skips (and does not wake) a sleeping disk. smartctl uses an
    # eight-bit status bitmask; its JSON stays useful for every normal result.
    nvme = device.startswith("/dev/nvme")
    no_power_check = role in power_check_disabled_roles()
    power_check = [] if no_power_check else ["-n", "standby"]
    text, error = run(["smartctl", *power_check, "-H", "-A", "-d", "nvme" if nvme else "sat", "--json=c", device],
                      timeout=45, accepted_statuses=set(range(256)))
    record["error"] = error
    if no_power_check:
        record["power_state"] = "unknown"
    if text is None:
        return record
    try:
        raw = json.loads(text)
        messages = smartctl_messages(raw)
        if not nvme and any(SAT_UNSUPPORTED.search(message) for message in messages):
            return scsi_health(record, device)
        power_rejected = no_power_check or any(POWER_CHECK_REJECTED.search(message) for message in messages)
        if not power_rejected and any(STANDBY_MESSAGE.search(message) for message in messages):
            record.update({"state": "standby", "error": None})
            return record
        if power_rejected:
            record["power_state"] = "unknown"
        smart_status = raw.get("smart_status")
        if not isinstance(smart_status, dict) or not isinstance(smart_status.get("passed"), bool):
            raise ValueError("SMART health status missing")
        if nvme:
            log = raw.get("nvme_smart_health_information_log")
            if not isinstance(log, dict):
                raise ValueError("NVMe health log missing")
            record.update({
                "state": "active", "smart_mode": "full", "type": "nvme", "passed": smart_status["passed"],
                "nvme": {key: int(log[key]) for key in ("percentage_used", "media_errors", "temperature")},
                "temperature": int(log["temperature"]),
                "error": None,
            })
            record.pop("crc_baseline", None)
            return record
        table = raw.get("ata_smart_attributes", {}).get("table")
        if not isinstance(table, list):
            raise ValueError("SMART attribute table missing")
        attributes = {
            str(item["id"]): int(item.get("raw", {}).get("value", 0))
            for item in table if isinstance(item, dict) and item.get("id") in {5, 197, 198, 199}
        }
        temperature = raw.get("temperature", {}).get("current") if isinstance(raw.get("temperature"), dict) else None
        record.update({
            "state": None if power_rejected else "active",
            "smart_mode": "full",
            "type": "sat",
            "passed": smart_status["passed"],
            "attributes": attributes,
            "temperature": temperature if isinstance(temperature, int) and not isinstance(temperature, bool) else None,
            "udma_crc_error_count_rise": attributes.get("199", 0) > previous.get(role, attributes.get("199", 0)),
            "error": None,
        })
        record.pop("crc_baseline", None)
    except (AttributeError, ValueError, TypeError, KeyError):
        record["error"] = "smartctl returned invalid JSON"
    return record


def disk_list() -> list[tuple[str, str]]:
    """Read role:filesystem-UUID pairs; the disk is resolved from the UUID at run time."""
    values = []
    for item in os.environ.get("STORAGE_TELEMETRY_DISKS", "").split():
        role, separator, uuid = item.partition(":")
        if separator and ROLE.fullmatch(role) and UUID.fullmatch(uuid):
            values.append((role, uuid))
    return values


def target_list() -> list[tuple[str, str, str]]:
    """Read role|mountpoint|expected UUID triplets from the root-owned unit config."""
    values = []
    for item in os.environ.get("STORAGE_TELEMETRY_TARGETS", "").split():
        parts = item.split("|", 2)
        if len(parts) == 3 and ROLE.fullmatch(parts[0]) and HOST_PATH.fullmatch(parts[1]) and UUID.fullmatch(parts[2]):
            values.append((parts[0], parts[1], parts[2]))
    return values


def host_read_only(path: str) -> bool | None:
    try:
        return bool(os.statvfs(path).f_flag & os.ST_RDONLY)
    except OSError:
        return None


def mount_records() -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    for role, mountpoint, expected_uuid in target_list():
        output, error = run(["findmnt", "-n", "-o", "UUID,FSTYPE", mountpoint], timeout=15)
        fields = [] if error else (output or "").split()
        # A filesystem without a UUID prints only its type; never read that as a UUID.
        actual_uuid, fstype = (fields[0], fields[1]) if len(fields) == 2 else (None, fields[0] if len(fields) == 1 else None)
        mounted = actual_uuid is not None and actual_uuid.lower() == expected_uuid.lower()
        records[role] = {"mounted": mounted, "uuid": actual_uuid, "fstype": fstype,
                         "read_only": host_read_only(mountpoint) if mounted else None}
    return records


def pool_list() -> list[tuple[str, str, list[str]]]:
    """Read role|mountpoint|branch:branch:... from the root-owned unit config."""
    values = []
    for item in os.environ.get("STORAGE_TELEMETRY_POOLS", "").split():
        parts = item.split("|", 2)
        if len(parts) != 3 or not ROLE.fullmatch(parts[0]) or not HOST_PATH.fullmatch(parts[1]):
            continue
        branches = parts[2].split(":")
        if branches and all(HOST_PATH.fullmatch(branch) for branch in branches):
            values.append((parts[0], parts[1], branches))
    return values


def mergerfs_value(mountpoint: str, key: str) -> str | None:
    try:
        return os.getxattr(os.path.join(mountpoint, MERGERFS_CONTROL), f"user.mergerfs.{key}").decode()
    except (OSError, UnicodeDecodeError):
        return None


# mergerfs runtime settings read from the pool's control file, by snapshot key.
MERGERFS_SETTINGS = {"create_policy": "category.create", "min_free_bytes": "minfreespace", "version": "version"}
UNLISTED_BRANCH = "unlisted"


def pool_records() -> dict[str, dict[str, object]]:
    """Verify each mergerfs pool by filesystem type and its exact, ordered branch list.

    findmnt's SOURCE for mergerfs is a shortened fsname, so the branches and
    settings come from mergerfs's own control file (the getxattr calls that
    `getfattr -n user.mergerfs.<key>` makes). mergerfs has no filesystem UUID.
    Branch paths are stored as target role names, never as paths.
    """
    roles_by_path = {path: role for role, path, _uuid in target_list()}
    records: dict[str, dict[str, object]] = {}
    for role, mountpoint, expected in pool_list():
        output, error = run(["findmnt", "-n", "-o", "FSTYPE", mountpoint], timeout=15)
        fstype = None if error else (output or "").strip() or None
        record: dict[str, object] = {"kind": "mergerfs", "fstype": fstype, "mounted": False, "branches": [],
                                     "unreadable": [], "error": None}
        records[role] = record
        if fstype != "fuse.mergerfs":
            record["error"] = "not a mergerfs mount"
            continue
        raw_branches = mergerfs_value(mountpoint, "branches")
        paths, branches = [], []
        for entry in (raw_branches or "").split(":"):
            path, _, options = entry.partition("=")
            if path:
                paths.append(path)
                branches.append({"role": roles_by_path.get(path, UNLISTED_BRANCH), "mode": options.split(",", 1)[0] or None})
        settings = {key: mergerfs_value(mountpoint, name) for key, name in MERGERFS_SETTINGS.items()}
        minfree = settings["min_free_bytes"]
        settings["min_free_bytes"] = int(minfree) if minfree and minfree.isdigit() else None
        record.update({
            "mounted": paths == expected, "branches": branches,
            "create_policy": settings["create_policy"][:32] if settings["create_policy"] else None,
            "min_free_bytes": settings["min_free_bytes"],
            "version": settings["version"][:32] if settings["version"] else None,
            "unreadable": (["branches"] if raw_branches is None else [])
                          + [key for key, value in settings.items() if value is None],
        })
    return records


def kernel_summary() -> dict[str, object]:
    text, error = run(["dmesg", "--since", "24 hours ago", "--color=never"], timeout=30)
    # Raw kernel lines can contain paths, UUIDs, serials, or other sensitive
    # host metadata. Only fixed-label counts and kernel device names persist.
    counts = dict.fromkeys(ERROR_PATTERNS, 0)
    devices: set[str] = set()
    for line in (text or "").splitlines():
        labels = [label for label, pattern in ERROR_PATTERNS.items() if pattern.search(line)]
        for label in labels:
            counts[label] += 1
        if labels:
            devices.update(DEVICE_NAME.findall(line))
    return {"window_hours": 24, "counts": counts, "devices": sorted(devices)[:MAX_KERNEL_DEVICES], "error": error}


def restic_snapshot() -> dict[str, object]:
    password_file = os.environ.get("RESTIC_PASSWORD_FILE", "")
    try:
        details = os.lstat(password_file)
    except OSError:
        return {"snapshots": [], "stats": None, "error": "RESTIC_PASSWORD_FILE is missing or unreadable"}
    # main() requires root, so the owner check means root-owned in production.
    if (not stat.S_ISREG(details.st_mode) or details.st_uid != os.geteuid()
            or stat.S_IMODE(details.st_mode) != 0o400):
        return {"snapshots": [], "stats": None, "error": "RESTIC_PASSWORD_FILE must be root-owned mode 0400"}
    env = {key: value for key, value in os.environ.items()
           if key in {"PATH", "RESTIC_REPOSITORY", "RESTIC_PASSWORD_FILE", "RESTIC_CACHE_DIR"}}
    text, error = run(["restic", "snapshots", "--json", "--no-lock"], env=env, timeout=600)
    if error:
        return {"snapshots": [], "stats": None, "error": error}
    try:
        snapshots = [item for item in json.loads(text or "[]") if isinstance(item, dict)]
    except (ValueError, TypeError):
        return {"snapshots": [], "stats": None, "error": "restic returned invalid JSON"}
    safe_snapshots = [{
        "id": str(item.get("short_id") or item.get("id", ""))[:64],
        "time": item.get("time"),
        "paths": [f"…/{Path(str(path)).name}" for path in (item.get("paths") or [])[:10]],
        "tags": [str(tag)[:80] for tag in (item.get("tags") or [])[:20]],
    } for item in snapshots[:200]]
    return {"snapshots": safe_snapshots, "stats": latest_summary(snapshots), "error": None}


def latest_summary(snapshots: list[dict]) -> dict[str, object] | None:
    """Size and file count from the newest snapshot's backup summary (restic 0.17+)."""
    dated = [item for item in snapshots if isinstance(item.get("time"), str)]
    if not dated:
        return None
    newest = max(dated, key=lambda item: item["time"])
    summary = newest.get("summary")
    if not isinstance(summary, dict):
        return None
    size, files = summary.get("total_bytes_processed"), summary.get("total_files_processed")
    if not all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (size, files)):
        return None
    return {"snapshot_id": str(newest.get("short_id") or newest.get("id", ""))[:64],
            "total_size": size, "total_file_count": files}


def main() -> int:
    if os.geteuid() != 0:
        raise SystemExit("collector must run as root")
    last_records = previous_smart_records()
    previous = previous_crc_counts(last_records)
    document = {
        "schema_version": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "smart": [smart_record(role, uuid, previous, last_records.get(role)) for role, uuid in disk_list()],
        "mounts": {**mount_records(), **pool_records()},
        "kernel": kernel_summary(),
        "restic": restic_snapshot(),
    }
    OUTPUT.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".storage-telemetry.", suffix=".json", dir=OUTPUT.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, OUTPUT)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
