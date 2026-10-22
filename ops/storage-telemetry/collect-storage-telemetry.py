#!/usr/bin/env python3
"""Collect bounded host storage health metadata into one atomic JSON snapshot."""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

OUTPUT = Path("/var/lib/omnibioai/storage-telemetry.json")
MAX_OUTPUT = 2 * 1024 * 1024
ERROR_PATTERNS = {
    "io_errors": re.compile(r"I/O error", re.IGNORECASE),
    "resets": re.compile(r"reset", re.IGNORECASE),
    "ext4_errors": re.compile(r"EXT4-fs error", re.IGNORECASE),
}
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


def previous_crc_counts() -> dict[str, int]:
    try:
        prior = json.loads(OUTPUT.read_text(encoding="utf-8"))
        return {
            str(item["role"]): int(item.get("attributes", {}).get("199", 0))
            for item in prior.get("smart", []) if isinstance(item, dict) and item.get("role")
        }
    except (OSError, ValueError, TypeError, KeyError):
        return {}


def smart_record(role: str, device: str, previous: dict[str, int]) -> dict[str, object]:
    # smartctl uses an eight-bit health bitmask; JSON remains useful for every
    # normal bitmask result, including failing attributes.
    text, error = run(["smartctl", "-H", "-A", "-d", "sat", "--json=c", device], timeout=45,
                      accepted_statuses=set(range(256)))
    record: dict[str, object] = {"role": role, "device": device, "passed": None, "attributes": {}, "error": error}
    if text is None:
        return record
    try:
        raw = json.loads(text)
        table = raw.get("ata_smart_attributes", {}).get("table")
        if not isinstance(table, list):
            raise ValueError("SMART attribute table missing")
        smart_status = raw.get("smart_status")
        if not isinstance(smart_status, dict) or not isinstance(smart_status.get("passed"), bool):
            raise ValueError("SMART health status missing")
        attributes = {
            str(item["id"]): int(item.get("raw", {}).get("value", 0))
            for item in table if isinstance(item, dict) and item.get("id") in {5, 197, 198, 199}
        }
        record.update({
            "passed": smart_status["passed"],
            "attributes": attributes,
            "udma_crc_error_count_rise": attributes.get("199", 0) > previous.get(role, attributes.get("199", 0)),
            "error": None,
        })
    except (ValueError, TypeError, KeyError):
        record["error"] = "smartctl returned invalid JSON"
    return record


def disk_list() -> list[tuple[str, str]]:
    values = []
    for item in os.environ.get("STORAGE_TELEMETRY_DISKS", "").split():
        role, separator, device = item.partition(":")
        if separator and re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", role) and re.fullmatch(r"/dev/[A-Za-z0-9._/-]+", device):
            values.append((role, device))
    return values


def target_list() -> list[tuple[str, str, str]]:
    """Read role|mountpoint|expected UUID triplets from the root-owned unit config."""
    values = []
    for item in os.environ.get("STORAGE_TELEMETRY_TARGETS", "").split():
        parts = item.split("|", 2)
        if (len(parts) == 3 and re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", parts[0])
                and re.fullmatch(r"/[A-Za-z0-9._/-]*", parts[1])
                and re.fullmatch(r"[A-Fa-f0-9-]{8,80}", parts[2])):
            values.append((parts[0], parts[1], parts[2]))
    return values


def mount_records() -> dict[str, dict[str, object]]:
    records = {}
    for role, mountpoint, expected_uuid in target_list():
        output, error = run(["findmnt", "-n", "-o", "UUID", mountpoint], timeout=15)
        actual_uuid = None if error else (output or "").strip() or None
        records[role] = {"mounted": actual_uuid == expected_uuid, "uuid": actual_uuid}
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
    snapshots_text, snapshots_error = run(["restic", "snapshots", "--json", "--no-lock"], env=env, timeout=600)
    stats_text, stats_error = run(["restic", "stats", "latest", "--json", "--no-lock"], env=env, timeout=600)
    if snapshots_error or stats_error:
        return {"snapshots": [], "stats": None, "error": snapshots_error or stats_error}
    try:
        snapshots = json.loads(snapshots_text or "[]")
        stats = json.loads(stats_text or "{}")
        safe_snapshots = [{
            "id": str(item.get("short_id") or item.get("id", ""))[:64],
            "time": item.get("time"),
            "paths": [f"…/{Path(path).name}" for path in item.get("paths", [])[:10]],
            "tags": [str(tag)[:80] for tag in item.get("tags", [])[:20]],
        } for item in snapshots[:200] if isinstance(item, dict)]
        safe_stats = {key: stats.get(key) for key in ("total_size", "total_file_count", "snapshots_count") if key in stats}
        return {"snapshots": safe_snapshots, "stats": safe_stats, "error": None}
    except (ValueError, TypeError):
        return {"snapshots": [], "stats": None, "error": "restic returned invalid JSON"}


def main() -> int:
    if os.geteuid() != 0:
        raise SystemExit("collector must run as root")
    previous = previous_crc_counts()
    document = {
        "schema_version": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "smart": [smart_record(role, device, previous) for role, device in disk_list()],
        "mounts": mount_records(),
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
