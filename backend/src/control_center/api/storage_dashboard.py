"""Read-only, bounded storage telemetry for the Admin Console.

The collector deliberately has no arbitrary command or path interface. It
reads a small set of Linux mount/device metadata sources and fixed configured
mountpoints. Host mount state is read only from explicit read-only host PID 1
bind mounts; container-local mountinfo must never be presented as host state.
Restic is queried only when an existing protected password file is configured;
the repository path and argument vector are fixed here.
"""

from __future__ import annotations

import json
import os
import re
import selectors
import shutil
import stat
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router_storage_dashboard = APIRouter(prefix="/storage", tags=["storage-dashboard"])

MAX_MOUNTINFO_BYTES = 2 * 1024 * 1024
MAX_FSTAB_BYTES = 256 * 1024
MAX_RESTIC_OUTPUT_BYTES = 1024 * 1024
RESTIC_TIMEOUT_SECONDS = 8
CACHE_TTL_SECONDS = 15
RESTIC_REPOSITORY = Path("/mnt/omnibioai-backup20tb/restic")
RESTIC_PASSWORD_FILE_ENV = "RESTIC_PASSWORD_FILE"
HOST_MOUNTINFO = Path("/run/host-storage/mountinfo")
HOST_FSTAB = Path("/run/host-storage/fstab")

# Paths are a fixed, bounded discovery set. Capacity and filesystem facts are
# always collected from the mounted filesystem; these entries do not encode
# capacities or claim that a path is mounted.
MOUNT_ROLES: tuple[tuple[str, str], ...] = (
    ("compute", "/"),
    ("primary", "/mnt/wdpro26tb"),
    ("backup", "/mnt/omnibioai-backup20tb"),
    ("archive-writable", "/mnt/omnibioai-archive22tb"),
    ("archive-member-a", "/media/manish/omnibioai-data"),
    ("archive-member-b", "/mnt/omnibioai-archive2tb-b"),
    ("archive-pool", "/mnt/omnibioai-archive"),
)
ROLE_LABELS = {
    "compute": "Compute",
    "primary": "Primary",
    "backup": "Backup",
    "archive-writable": "Archive writable branch",
    "archive-member-a": "Archive read-only branch A",
    "archive-member-b": "Archive read-only branch B",
    "archive-pool": "Archive pool",
}
PHYSICAL_ROLES = {role for role, _ in MOUNT_ROLES if role != "archive-pool"}
ARCHIVE_ROLES = {"archive-writable", "archive-member-a", "archive-member-b"}

HealthState = Literal["HEALTHY", "WARNING", "CRITICAL", "UNKNOWN", "STALE"]
GateState = Literal["PASS", "PARTIAL", "FAIL", "BLOCKED", "NOT_VERIFIED"]


class SourceState(BaseModel):
    status: Literal["AVAILABLE", "PARTIAL", "UNAVAILABLE"]
    observed_at: str
    detail: str


class DeviceVolume(BaseModel):
    role: str
    label: str
    device_identity: str | None = None
    filesystem_uuid: str | None = None
    filesystem: str | None = None
    mount_point: str
    mount_status: Literal["MOUNTED", "MISSING", "UNKNOWN"]
    mount_mode: Literal["READ_ONLY", "READ_WRITE", "UNKNOWN"]
    total_bytes: int | None = None
    used_bytes: int | None = None
    available_bytes: int | None = None
    utilization_percent: float | None = None
    mount_options: list[str] = []
    transport: str | None = None
    transport_topology: str | None = None
    smart_status: Literal["AVAILABLE", "UNAVAILABLE", "UNKNOWN"] = "UNKNOWN"
    health: HealthState = "UNKNOWN"
    health_detail: str = "Health telemetry unavailable"
    last_observed_error: str | None = None
    last_successful_observation: str | None = None
    aggregate: bool = False


class ArchiveBranch(BaseModel):
    mount_point: str
    role: str
    expected_mode: Literal["READ_ONLY", "READ_WRITE", "UNKNOWN"]
    observed_mode: Literal["READ_ONLY", "READ_WRITE", "UNKNOWN"]
    mount_status: Literal["MOUNTED", "MISSING", "UNKNOWN"]
    filesystem: str | None = None
    filesystem_uuid: str | None = None
    total_bytes: int | None = None
    available_bytes: int | None = None


class ArchiveTelemetry(BaseModel):
    pool_mount_point: str
    pool_status: Literal["MOUNTED", "MISSING", "UNKNOWN"]
    total_bytes: int | None = None
    used_bytes: int | None = None
    available_bytes: int | None = None
    utilization_percent: float | None = None
    branches: list[ArchiveBranch]
    create_policy: str | None = None
    min_free_bytes: int | None = None
    min_free_policy_status: Literal["CONFIGURED", "NOT_CONFIGURED", "UNKNOWN"]
    dependencies: list[str]
    dependency_assessment: Literal["CONFIGURED", "NOT_VERIFIED", "WARNING"]
    configured_source: str
    dependency_note: str
    runtime_policy_status: Literal["VERIFIED", "NOT_VERIFIED"]


class SnapshotItem(BaseModel):
    id: str
    time: str
    age_seconds: int | None = None
    source_paths: list[str]
    tags: list[str]


class BackupTelemetry(BaseModel):
    repository_status: Literal["AVAILABLE", "UNAVAILABLE", "PARTIAL"]
    repository_id: str | None = None
    snapshot_count: int | None = None
    snapshots_truncated: bool = False
    snapshots: list[SnapshotItem]
    latest_snapshot_at: str | None = None
    schedule_status: Literal["AVAILABLE", "MISSING", "UNKNOWN"]
    schedules: list[str]
    retention_status: Literal["AVAILABLE", "MISSING", "UNKNOWN"]
    retention_summary: str | None = None
    restore_verification: GateState
    observed_at: str
    detail: str


class HealthAlert(BaseModel):
    id: str
    state: Literal["ACTIVE", "HISTORICAL"]
    severity: Literal["WARNING", "CRITICAL"]
    affected_device: str | None = None
    source: str
    observed_at: str
    evidence: str
    suggested_action: str


class ReadinessGate(BaseModel):
    id: str
    label: str
    state: GateState
    evidence_source: str
    observed_at: str
    explanation: str


class StorageOverview(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    observed_at: str
    freshness: Literal["CURRENT", "STALE", "UNKNOWN"]
    sources: dict[str, SourceState]
    physical_devices: list[DeviceVolume]
    archive_pool: ArchiveTelemetry
    backups: BackupTelemetry
    alerts: list[HealthAlert]
    readiness_gates: list[ReadinessGate]
    readiness_state: Literal["READY", "NOT_READY", "NOT_VERIFIED"]


class DevicesResponse(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    observed_at: str
    freshness: Literal["CURRENT", "STALE", "UNKNOWN"]
    source: SourceState
    devices: list[DeviceVolume]


class ArchiveResponse(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    observed_at: str
    freshness: Literal["CURRENT", "STALE", "UNKNOWN"]
    source: SourceState
    archive: ArchiveTelemetry


class BackupsResponse(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    observed_at: str
    freshness: Literal["CURRENT", "STALE", "UNKNOWN"]
    source: SourceState
    backups: BackupTelemetry


class HealthResponse(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    observed_at: str
    freshness: Literal["CURRENT", "STALE", "UNKNOWN"]
    alerts: list[HealthAlert]


class ReadinessResponse(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    observed_at: str
    freshness: Literal["CURRENT", "STALE", "UNKNOWN"]
    overall: Literal["READY", "NOT_READY", "NOT_VERIFIED"]
    gates: list[ReadinessGate]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unescape_mount(value: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), value)


def _read_bounded(path: Path, limit: int) -> str | None:
    try:
        with path.open("rb") as handle:
            raw = handle.read(limit + 1)
        if len(raw) > limit:
            return None
        return raw.decode("utf-8", errors="replace")
    except OSError:
        return None


def parse_mountinfo(text: str) -> dict[str, dict[str, object]]:
    """Parse /proc/self/mountinfo into mountpoint-keyed observations."""
    result: dict[str, dict[str, object]] = {}
    for line in text.splitlines():
        fields = line.split()
        try:
            separator = fields.index("-")
            if separator < 6 or len(fields) < separator + 4:
                continue
            mount_point = _unescape_mount(fields[4])
            mount_options = fields[5].split(",")
            major_minor = fields[2]
            if not re.fullmatch(r"\d+:\d+", major_minor):
                continue
            result[mount_point] = {
                "major_minor": major_minor,
                "root": _unescape_mount(fields[3]),
                "options": mount_options,
                "filesystem": fields[separator + 1],
                "source": _unescape_mount(fields[separator + 2]),
                "super_options": fields[separator + 3].split(","),
            }
        except (ValueError, IndexError):
            continue
    return result


def parse_fstab(text: str) -> dict[str, dict[str, object]]:
    """Parse fstab without invoking mount or accepting caller-supplied paths."""
    result: dict[str, dict[str, object]] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        if len(fields) < 4:
            continue
        source, target, filesystem, options = fields[:4]
        target = _unescape_mount(target)
        option_list = [_unescape_mount(item) for item in options.split(",")]
        result[target] = {
            "source": _unescape_mount(source),
            "filesystem": filesystem,
            "options": option_list,
        }
    return result


def _read_uuid_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    base = Path("/dev/disk/by-uuid")
    try:
        with os.scandir(base) as entries:
            for index, entry in enumerate(entries):
                if index >= 512:
                    break
                try:
                    if entry.is_symlink():
                        # Match the UUID link to mountinfo's kernel device
                        # number. This avoids depending on /dev/sdX aliases or
                        # symlink target spelling, both of which can change.
                        details = os.stat(entry.path)
                        if stat.S_ISBLK(details.st_mode):
                            device = f"{os.major(details.st_rdev)}:{os.minor(details.st_rdev)}"
                            mapping[device] = entry.name
                except OSError:
                    continue
    except OSError:
        pass
    return mapping


def _read_sysfs_device(major_minor: str) -> tuple[str | None, str | None]:
    if not re.fullmatch(r"\d+:\d+", major_minor):
        return None, None
    base = Path("/sys/dev/block") / major_minor
    try:
        resolved = base.resolve(strict=True)
    except OSError:
        return None, None
    model = None
    for candidate in (resolved / "device" / "model", resolved.parent / "device" / "model"):
        value = _read_bounded(candidate, 256)
        if value:
            model = value.strip()[:128] or None
            if model:
                break
    # Keep USB topology stable without publishing serials/WWNs.
    topology = None
    try:
        relative = resolved.as_posix().split("/sys/devices/", 1)[1]
        if "usb" in relative.lower():
            topology = "/sys/devices/" + "/".join(relative.split("/")[:8])
    except (IndexError, OSError):
        pass
    return model, topology


def _fstab_options(entry: dict[str, object] | None) -> list[str]:
    return list(entry.get("options", [])) if entry else []


def _mount_mode(options: list[str]) -> Literal["READ_ONLY", "READ_WRITE", "UNKNOWN"]:
    if "ro" in options:
        return "READ_ONLY"
    if "rw" in options:
        return "READ_WRITE"
    return "UNKNOWN"


def _capacity(mount_point: str) -> tuple[int | None, int | None, int | None, float | None]:
    try:
        statvfs = os.statvfs(mount_point)
        total = statvfs.f_blocks * statvfs.f_frsize
        available = statvfs.f_bavail * statvfs.f_frsize
        used = max(0, total - statvfs.f_bfree * statvfs.f_frsize)
        pct = round((used / total) * 100, 1) if total else None
        return total, used, available, pct
    except OSError:
        return None, None, None, None


def _device_records(
    mounts: dict[str, dict[str, object]], fstab: dict[str, dict[str, object]],
    *, capacity_from_collector_namespace: bool = True,
) -> list[DeviceVolume]:
    uuid_by_device = _read_uuid_map()
    devices: list[DeviceVolume] = []
    for role, mount_point in MOUNT_ROLES:
        mount = mounts.get(mount_point)
        configured = fstab.get(mount_point)
        if mount is None:
            devices.append(DeviceVolume(
                role=role, label=ROLE_LABELS[role], mount_point=mount_point,
                mount_status="MISSING" if configured else "UNKNOWN", mount_mode="UNKNOWN",
                health="UNKNOWN", health_detail="Mount is not present in the collector namespace",
                aggregate=(role == "archive-pool"),
            ))
            continue
        options = list(mount["options"])
        # Superblock mode is often more useful for FUSE/overlay mounts.
        super_options = list(mount["super_options"])
        observed_mode = _mount_mode(options + super_options)
        major_minor = str(mount["major_minor"])
        model, topology = _read_sysfs_device(major_minor)
        uuid = uuid_by_device.get(major_minor)
        # statvfs in a container describes its namespace even when mountinfo
        # was supplied from the host. Keep capacity unknown until a separately
        # attested host capacity source is available.
        total, used, available, percent = _capacity(mount_point) if capacity_from_collector_namespace else (None, None, None, None)
        health: HealthState = "UNKNOWN"
        detail = "SMART telemetry unavailable to this service"
        if percent is not None:
            if percent >= 95:
                health, detail = "CRITICAL", "Filesystem utilization is at least 95%"
            elif percent >= 85:
                health, detail = "WARNING", "Filesystem utilization is at least 85%"
        if health == "UNKNOWN" and observed_mode == "READ_ONLY" and _mount_mode(_fstab_options(configured)) == "READ_WRITE":
            health, detail = "WARNING", "Mounted read-only although fstab does not declare read-only"
        devices.append(DeviceVolume(
            role=role,
            label=ROLE_LABELS[role],
            device_identity=model,
            filesystem_uuid=uuid,
            filesystem=str(mount["filesystem"]),
            mount_point=mount_point,
            mount_status="MOUNTED",
            mount_mode=observed_mode,
            total_bytes=total,
            used_bytes=used,
            available_bytes=available,
            utilization_percent=percent,
            mount_options=list(dict.fromkeys(options + super_options)),
            transport="USB" if topology else None,
            transport_topology=topology,
            smart_status="UNAVAILABLE",
            health=health,
            health_detail=detail,
            last_successful_observation=_now(),
            aggregate=(role == "archive-pool"),
        ))
    return devices


def _archive_data(devices: list[DeviceVolume], fstab: dict[str, dict[str, object]]) -> ArchiveTelemetry:
    by_role = {device.role: device for device in devices}
    pool = by_role["archive-pool"]
    pool_mount = fstab.get("/mnt/omnibioai-archive", {})
    pool_source = str(pool_mount.get("source", ""))
    branch_modes: dict[str, Literal["READ_ONLY", "READ_WRITE"]] = {}
    for configured_branch in pool_source.split(":"):
        branch_path, marker, branch_mode = configured_branch.rpartition("=")
        if marker and branch_mode in {"RW", "RO"} and branch_path.startswith("/"):
            branch_modes[branch_path] = "READ_WRITE" if branch_mode == "RW" else "READ_ONLY"
    branches: list[ArchiveBranch] = []
    branch_roles = ["archive-writable", "archive-member-a", "archive-member-b"]
    for role in branch_roles:
        device = by_role[role]
        expected = branch_modes.get(device.mount_point, "UNKNOWN")
        branches.append(ArchiveBranch(
            mount_point=device.mount_point,
            role=role,
            expected_mode=expected,
            observed_mode=device.mount_mode,
            mount_status=device.mount_status,
            filesystem=device.filesystem,
            filesystem_uuid=device.filesystem_uuid,
            total_bytes=device.total_bytes,
            available_bytes=device.available_bytes,
        ))
    options = _fstab_options(pool_mount)
    create_policy = next((item.split("=", 1)[1] for item in options if item.startswith("category.create=")), None)
    min_free = None
    min_free_status: Literal["CONFIGURED", "NOT_CONFIGURED", "UNKNOWN"] = "NOT_CONFIGURED" if pool_mount else "UNKNOWN"
    for item in options:
        if item.startswith("minfreespace="):
            try:
                value = item.split("=", 1)[1]
                multiplier = 1
                if value[-1:].lower() in {"k", "m", "g", "t"}:
                    multiplier = {"k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}[value[-1].lower()]
                    value = value[:-1]
                min_free = int(value) * multiplier
                min_free_status = "CONFIGURED"
            except (ValueError, IndexError):
                min_free_status = "UNKNOWN"
    dependencies = [item.split("=", 1)[1] for item in options if item.startswith("x-systemd.requires-mounts-for=")]
    missing = [branch.mount_point for branch in branches if branch.mount_status == "MISSING"]
    return ArchiveTelemetry(
        pool_mount_point=pool.mount_point,
        pool_status=pool.mount_status,
        total_bytes=pool.total_bytes,
        used_bytes=pool.used_bytes,
        available_bytes=pool.available_bytes,
        utilization_percent=pool.utilization_percent,
        branches=branches,
        create_policy=create_policy,
        min_free_bytes=min_free,
        min_free_policy_status=min_free_status,
        dependencies=dependencies,
        dependency_assessment="WARNING" if missing or any(path in dependencies for path in ("/media/manish/omnibioai-data", "/mnt/omnibioai-archive2tb-b")) else ("CONFIGURED" if dependencies else "NOT_VERIFIED"),
        configured_source="/etc/fstab in collector namespace",
        dependency_note=("Optional read-only member mount requirements are declared; startup dependency is visible, disconnect propagation is not verified." if any(path in dependencies for path in ("/media/manish/omnibioai-data", "/mnt/omnibioai-archive2tb-b")) else "Systemd dependency behavior is not verified from this collector."),
        runtime_policy_status="NOT_VERIFIED",
    )


def _secure_password_file() -> Path | None:
    value = os.environ.get(RESTIC_PASSWORD_FILE_ENV)
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        return None
    try:
        details = path.lstat()
        if not stat.S_ISREG(details.st_mode) or stat.S_ISLNK(details.st_mode):
            return None
        if details.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            return None
        if details.st_uid not in {0, os.geteuid()} or not os.access(path, os.R_OK):
            return None
        return path
    except OSError:
        return None


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    """Stop and reap a child with a bounded wait, including timeout paths."""
    try:
        if process.poll() is None:
            process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        # Do not turn a telemetry timeout into an unbounded request wait.
        # Popen will arrange eventual child reaping if the process exits later.
        pass


def _bounded_process(argv: list[str], env: dict[str, str], timeout: int, max_bytes: int) -> tuple[str | None, str]:
    """Run a fixed argv with bounded stdout, deadline, no stdin, and hidden stderr."""
    process: subprocess.Popen[bytes] | None = None
    selector: selectors.BaseSelector | None = None
    output = bytearray()
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            close_fds=True,
        )
        if process.stdout is None:
            return None, "output_unavailable"
        os.set_blocking(process.stdout.fileno(), False)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _stop_process(process)
                return None, "timeout"
            events = selector.select(min(remaining, 0.2))
            for key, _ in events:
                chunk = os.read(key.fd, min(65536, max_bytes + 1 - len(output)))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output.extend(chunk)
                if len(output) > max_bytes:
                    _stop_process(process)
                    return None, "output_limit"
            if process.poll() is not None and not selector.get_map():
                break
        if process.wait(timeout=max(0.1, deadline - time.monotonic())) != 0:
            return None, "command_failed"
        return output.decode("utf-8", errors="strict"), "ok"
    except subprocess.TimeoutExpired:
        if process is not None:
            _stop_process(process)
        return None, "timeout"
    except (OSError, UnicodeDecodeError, ValueError):
        if process is not None and process.poll() is None:
            _stop_process(process)
        return None, "collector_error"
    finally:
        if selector is not None:
            selector.close()
        if process is not None and process.stdout is not None:
            process.stdout.close()


def parse_restic_snapshots(text: str, now: datetime | None = None) -> tuple[list[SnapshotItem], str | None, bool]:
    """Parse and redact Restic JSON; never return raw paths or repository secrets."""
    moment = now or datetime.now(timezone.utc)
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return [], None, False
    if not isinstance(raw, list):
        return [], None, False
    snapshots: list[SnapshotItem] = []
    for item in raw[:200]:
        if not isinstance(item, dict):
            continue
        snapshot_id = item.get("short_id") or item.get("id")
        timestamp = item.get("time")
        if not isinstance(snapshot_id, str) or not isinstance(timestamp, str):
            continue
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            age = max(0, int((moment - parsed).total_seconds()))
        except ValueError:
            age = None
        raw_paths = item.get("paths")
        paths = []
        if isinstance(raw_paths, list):
            paths = [f"…/{Path(path).name}" for path in raw_paths[:10] if isinstance(path, str) and Path(path).name]
        raw_tags = item.get("tags")
        tags = [tag[:80] for tag in raw_tags[:20] if isinstance(tag, str)] if isinstance(raw_tags, list) else []
        snapshots.append(SnapshotItem(id=snapshot_id[:64], time=timestamp, age_seconds=age, source_paths=paths, tags=tags))
    latest = max((item.time for item in snapshots), default=None)
    return snapshots, latest, len(raw) > 200


def _restic_data(observed_at: str) -> BackupTelemetry:
    password_file = _secure_password_file()
    restic = next((path for path in ("/usr/bin/restic", "/usr/local/bin/restic") if os.path.isfile(path) and os.access(path, os.X_OK)), None)
    if not password_file:
        return BackupTelemetry(
            repository_status="UNAVAILABLE", snapshots=[], schedule_status="UNKNOWN", schedules=[],
            retention_status="UNKNOWN", restore_verification="NOT_VERIFIED", observed_at=observed_at,
            detail="Noninteractive protected RESTIC_PASSWORD_FILE is not configured or not accessible; no Restic command was run.",
        )
    if not restic or not RESTIC_REPOSITORY.is_dir() or not os.access(RESTIC_REPOSITORY, os.R_OK | os.X_OK):
        return BackupTelemetry(
            repository_status="UNAVAILABLE", snapshots=[], schedule_status="UNKNOWN", schedules=[],
            retention_status="UNKNOWN", restore_verification="NOT_VERIFIED", observed_at=observed_at,
            detail="Restic executable or fixed repository is unavailable to this service.",
        )
    env = {"PATH": "/usr/bin:/bin", RESTIC_PASSWORD_FILE_ENV: str(password_file)}
    text, result = _bounded_process(
        [restic, "--no-lock", "--no-cache", "-r", str(RESTIC_REPOSITORY), "snapshots", "--json"],
        env, RESTIC_TIMEOUT_SECONDS, MAX_RESTIC_OUTPUT_BYTES,
    )
    if result != "ok" or text is None:
        safe_reason = {
            "timeout": "Restic inventory collection timed out.",
            "output_limit": "Restic inventory exceeded the configured output limit.",
            "command_failed": "Restic inventory command failed; stderr is suppressed.",
        }.get(result, "Restic inventory is unavailable; command output is suppressed.")
        return BackupTelemetry(
            repository_status="UNAVAILABLE", snapshots=[], schedule_status="UNKNOWN", schedules=[],
            retention_status="UNKNOWN", restore_verification="NOT_VERIFIED", observed_at=observed_at,
            detail=safe_reason,
        )
    snapshots, latest, truncated = parse_restic_snapshots(text)
    if not snapshots and text.strip() not in {"[]", "null"}:
        status: Literal["AVAILABLE", "PARTIAL", "UNAVAILABLE"] = "PARTIAL"
        detail = "Restic returned malformed or empty snapshot metadata."
    else:
        status, detail = "AVAILABLE", "Snapshot inventory collected read-only."
    return BackupTelemetry(
        repository_status=status,
        snapshots=snapshots,
        snapshot_count=None if truncated else len(snapshots),
        snapshots_truncated=truncated,
        latest_snapshot_at=latest,
        schedule_status="UNKNOWN",
        schedules=[],
        retention_status="UNKNOWN",
        restore_verification="NOT_VERIFIED",
        observed_at=observed_at,
        detail=detail,
    )


def _schedule_inventory() -> tuple[Literal["AVAILABLE", "MISSING", "UNKNOWN"], list[str]]:
    """Read only matching timer/cron schedule expressions, never job commands."""
    schedules: list[str] = []
    inspected = False
    for directory in (Path("/etc/systemd/system"), Path("/lib/systemd/system"), Path("/usr/lib/systemd/system")):
        try:
            with os.scandir(directory) as entries:
                for index, entry in enumerate(entries):
                    if index >= 512:
                        break
                    if not entry.name.endswith(".timer") or not re.search(r"backup|restic|archive|snapshot", entry.name, re.I):
                        continue
                    inspected = True
                    content = _read_bounded(Path(entry.path), 32 * 1024)
                    if content is None:
                        continue
                    calendars = [line.split("=", 1)[1].strip() for line in content.splitlines()
                                 if line.strip().startswith("OnCalendar=")]
                    for calendar in calendars[:4]:
                        # Unit names and calendar expressions only; no ExecStart or credential values.
                        schedules.append(f"{entry.name}: {calendar} (unit-file activation unverified)")
        except OSError:
            continue
    directory = Path("/etc/cron.d")
    try:
        with os.scandir(directory) as entries:
            for index, entry in enumerate(entries):
                if index >= 256:
                    break
                if not entry.is_file(follow_symlinks=False):
                    continue
                inspected = True
                content = _read_bounded(Path(entry.path), 32 * 1024)
                if content is None:
                    continue
                for line in content.splitlines():
                    if line.lstrip().startswith("#") or not re.search(r"restic|backup|archive|snapshot", line, re.I):
                        continue
                    fields = line.split()
                    if len(fields) >= 6:
                        schedules.append(f"{entry.name}: {' '.join(fields[:6])} (cron expression; command redacted)")
    except OSError:
        pass
    # Periodic directories express cadence by their directory name. Only
    # matching filenames are reported; file contents are not inspected.
    for directory in (Path("/etc/cron.daily"), Path("/etc/cron.weekly"), Path("/etc/cron.monthly")):
        try:
            with os.scandir(directory) as entries:
                for index, entry in enumerate(entries):
                    if index >= 256:
                        break
                    if not re.search(r"restic|backup|archive|snapshot", entry.name, re.I):
                        continue
                    inspected = True
                    schedules.append(f"{directory.name}/{entry.name}: {directory.name.removeprefix('cron.')} (activation unverified)")
        except OSError:
            continue
    if schedules:
        return "AVAILABLE", sorted(set(schedules))[:40]
    return ("MISSING", []) if inspected else ("UNKNOWN", [])


def _health_alerts(devices: list[DeviceVolume], archive: ArchiveTelemetry, backups: BackupTelemetry, observed_at: str) -> list[HealthAlert]:
    alerts: list[HealthAlert] = []
    for device in devices:
        if device.mount_status == "MISSING":
            alerts.append(HealthAlert(
                id=f"mount-missing:{device.role}", state="ACTIVE", severity="CRITICAL",
                affected_device=device.label, source="host PID 1 mountinfo bind",
                observed_at=observed_at, evidence=f"Expected host mount {device.mount_point} is absent from the supplied host mount table.",
                suggested_action="Verify the host mount and bind provenance before changing storage configuration.",
            ))
        elif device.health in {"WARNING", "CRITICAL"}:
            alerts.append(HealthAlert(
                id=f"capacity:{device.role}", state="ACTIVE", severity=device.health,
                affected_device=device.label, source="statvfs",
                observed_at=observed_at, evidence=device.health_detail,
                suggested_action=("Review available capacity and workload growth; do not delete data automatically." if "utilization" in device.health_detail else "Verify mount mode and host mount identity before changing configuration."),
            ))
    missing_branches = [branch for branch in archive.branches if branch.mount_status == "MISSING"]
    for branch in missing_branches:
        alerts.append(HealthAlert(
            id=f"archive-branch:{branch.role}", state="ACTIVE", severity="WARNING",
            affected_device=branch.mount_point, source="host PID 1 mountinfo bind",
            observed_at=observed_at, evidence="Configured archive branch is not mounted in the supplied host mount table.",
            suggested_action="Confirm the member mount and pool dependency behavior; preserve member contents.",
        ))
    if backups.repository_status == "UNAVAILABLE":
        alerts.append(HealthAlert(
            id="restic-unavailable", state="ACTIVE", severity="WARNING", affected_device=None,
            source="Restic collector", observed_at=observed_at, evidence=backups.detail,
            suggested_action="Configure an approved noninteractive, least-privilege password-file mechanism or keep repository telemetry unavailable.",
        ))
    return alerts


GATE_DEFINITIONS = (
    ("nvme-health", "NVMe health", "sysfs/NVMe SMART", "BLOCKED", "Health and wear indicators require device access not available to this service."),
    ("device-identification", "Device identification", "Host PID 1 mountinfo bind + /dev/disk/by-uuid", "PARTIAL", "Host mount identity requires verified bind provenance; UUID and USB topology may be unavailable to this service."),
    ("mount-integrity", "Mount verification", "Host PID 1 mountinfo bind", "PARTIAL", "A read-only host mount table can show current mounts; it does not prove long-term stability or capacity."),
    ("primary-reliability", "Primary disk reliability", "SMART + kernel log", "BLOCKED", "SMART and kernel I/O evidence are not available to this service."),
    ("archive-integrity", "Archive filesystem integrity", "Filesystem health evidence", "NOT_VERIFIED", "A mounted filesystem is not proof of integrity."),
    ("mergerfs-resilience", "Mergerfs resilience", "fstab + runtime mount", "PARTIAL", "Configured branches can be compared with mounts; failover behavior requires isolated testing."),
    ("restic-access", "Restic repository access", "Restic read-only inventory", "PARTIAL", "Only available when the protected noninteractive credential mechanism is configured."),
    ("snapshot-inventory", "Snapshot inventory", "Restic snapshots", "PARTIAL", "Inventory is not verified when Restic access is unavailable."),
    ("snapshot-integrity", "Snapshot integrity", "Restic check", "NOT_VERIFIED", "No repository integrity scan is run by this dashboard."),
    ("isolated-restore", "Isolated restore", "Operator qualification record", "NOT_VERIFIED", "No restore verification evidence source is configured."),
    ("backup-schedule", "Backup scheduling", "systemd/cron inventory", "NOT_VERIFIED", "Schedule discovery is not yet connected to a trusted status source."),
    ("retention", "Retention policy", "Restic policy configuration", "NOT_VERIFIED", "Retention policy is not inferred from snapshot presence."),
    ("workload-placement", "Workload placement", "Docker/storage mapping", "NOT_VERIFIED", "Docker socket and workload volume mappings are intentionally not collected."),
    ("workbench-integration", "Workbench storage integration", "Workbench acceptance evidence", "NOT_VERIFIED", "No current acceptance artifact is configured."),
)


def _readiness(observed_at: str, backups: BackupTelemetry | None = None) -> list[ReadinessGate]:
    values = [ReadinessGate(
        id=gate_id, label=label, state=state, evidence_source=source,
        observed_at=observed_at, explanation=explanation,
    ) for gate_id, label, source, state, explanation in GATE_DEFINITIONS]
    if backups is not None:
        by_id = {gate.id: gate for gate in values}
        access = by_id["restic-access"]
        inventory = by_id["snapshot-inventory"]
        access.state = "PASS" if backups.repository_status == "AVAILABLE" else "PARTIAL" if backups.repository_status == "PARTIAL" else "BLOCKED"
        access.explanation = backups.detail
        if backups.repository_status == "UNAVAILABLE":
            inventory.state = "BLOCKED"
            inventory.explanation = backups.detail
        elif backups.repository_status == "PARTIAL":
            inventory.state = "PARTIAL"
            inventory.explanation = backups.detail
        elif backups.snapshot_count == 0:
            inventory.state = "FAIL"
            inventory.explanation = "The repository was accessible, but no snapshots were returned."
        elif backups.snapshots_truncated:
            inventory.state = "PARTIAL"
            inventory.explanation = "Snapshot inventory was collected but truncated at the configured response bound."
        else:
            inventory.state = "PASS"
            inventory.explanation = "Snapshot inventory was collected read-only."
        access.evidence_source = "Restic read-only snapshots command"
        inventory.evidence_source = "Restic snapshots JSON"
    return values


_cache_lock = threading.Lock()
_cache: tuple[float, StorageOverview] | None = None


def _collect() -> StorageOverview:
    observed_at = _now()
    # These exact paths must be read-only binds of host /proc/1/mountinfo and
    # /etc/fstab, verified from Docker's mount configuration at deployment.
    # An absent or incomplete pair fails closed; never fall back to /proc/self.
    mount_text = _read_bounded(HOST_MOUNTINFO, MAX_MOUNTINFO_BYTES)
    fstab_text = _read_bounded(HOST_FSTAB, MAX_FSTAB_BYTES)
    if mount_text is None or fstab_text is None:
        mount_text = None
        fstab_text = None
    mounts = parse_mountinfo(mount_text or "")
    fstab = parse_fstab(fstab_text or "")
    devices = _device_records(mounts, fstab, capacity_from_collector_namespace=False)
    archive = _archive_data(devices, fstab)
    archive.configured_source = "Host /etc/fstab read-only bind" if fstab_text is not None else "Host fstab unavailable"
    backups = _restic_data(observed_at)
    schedule_status, schedules = _schedule_inventory()
    backups.schedule_status = schedule_status
    backups.schedules = schedules
    alerts = _health_alerts(devices, archive, backups, observed_at)
    sources = {
        "mounts": SourceState(
            status="PARTIAL" if mount_text is not None else "UNAVAILABLE",
            observed_at=observed_at,
            detail="Read bounded host PID 1 mountinfo bind; capacity and bind provenance require separate verification" if mount_text is not None else "Host mountinfo/fstab read-only bind pair is absent or unreadable; container mounts were not used",
        ),
        "configuration": SourceState(
            status="PARTIAL" if fstab_text is not None else "UNAVAILABLE",
            observed_at=observed_at,
            detail="Read bounded host fstab bind; bind provenance requires separate verification" if fstab_text is not None else "Host mountinfo/fstab read-only bind pair is absent or unreadable; container configuration was not used",
        ),
        "smart": SourceState(status="UNAVAILABLE", observed_at=observed_at, detail="No privileged SMART helper is configured"),
        "restic": SourceState(status=backups.repository_status, observed_at=observed_at, detail=backups.detail),
        "docker": SourceState(status="UNAVAILABLE", observed_at=observed_at, detail="Docker socket is not accessed by this collector"),
    }
    all_required_sources = mount_text is not None and fstab_text is not None
    return StorageOverview(
        observed_at=observed_at,
        freshness="CURRENT" if all_required_sources else "UNKNOWN",
        sources=sources,
        physical_devices=[device for device in devices if device.role in PHYSICAL_ROLES],
        archive_pool=archive,
        backups=backups,
        alerts=alerts,
        readiness_gates=_readiness(observed_at, backups),
        readiness_state="NOT_VERIFIED",
    )


def get_snapshot(force_refresh: bool = False) -> StorageOverview:
    global _cache
    now = time.monotonic()
    with _cache_lock:
        if not force_refresh and _cache and now - _cache[0] < CACHE_TTL_SECONDS:
            return _cache[1]
        try:
            snapshot = _collect()
        except Exception:
            if _cache is not None:
                return _cache[1].copy(update={"freshness": "STALE"})
            observed_at = _now()
            unavailable_devices = [DeviceVolume(
                role=role, label=ROLE_LABELS[role], mount_point=mount_point,
                mount_status="UNKNOWN", mount_mode="UNKNOWN", health="UNKNOWN",
                health_detail="Collector failed before this source could be observed",
                aggregate=(role == "archive-pool"),
            ) for role, mount_point in MOUNT_ROLES]
            unavailable_archive = ArchiveTelemetry(
                pool_mount_point="/mnt/omnibioai-archive", pool_status="UNKNOWN", branches=[],
                create_policy=None, min_free_bytes=None, min_free_policy_status="UNKNOWN",
                dependencies=[], dependency_assessment="NOT_VERIFIED",
                configured_source="Unavailable", dependency_note="Collector failed; dependencies were not observed.",
                runtime_policy_status="NOT_VERIFIED",
            )
            unavailable_backups = BackupTelemetry(
                repository_status="UNAVAILABLE", snapshots=[], schedule_status="UNKNOWN", schedules=[],
                retention_status="UNKNOWN", restore_verification="NOT_VERIFIED", observed_at=observed_at,
                detail="Collector failed before Restic metadata could be observed.",
            )
            return StorageOverview(
                observed_at=observed_at, freshness="UNKNOWN",
                sources={name: SourceState(status="UNAVAILABLE", observed_at=observed_at, detail="Collector failed; telemetry unavailable")
                         for name in ("mounts", "configuration", "smart", "restic", "docker")},
                physical_devices=[device for device in unavailable_devices if device.role in PHYSICAL_ROLES],
                archive_pool=unavailable_archive, backups=unavailable_backups, alerts=[],
                readiness_gates=_readiness(observed_at, unavailable_backups), readiness_state="NOT_VERIFIED",
            )
        _cache = (time.monotonic(), snapshot)
        return snapshot


EXPECTED_SOURCES = ("mounts", "configuration", "smart", "restic", "docker")
GATE_SOURCES = {
    "device-identification": ("mounts",),
    "mount-integrity": ("mounts",),
    "primary-reliability": ("smart",),
    "archive-integrity": ("mounts",),
    "mergerfs-resilience": ("mounts", "configuration"),
    "restic-access": ("restic",),
    "snapshot-inventory": ("restic",),
    "snapshot-integrity": ("restic",),
    "isolated-restore": ("restic",),
}


def _source_state(snapshot: StorageOverview, name: str) -> SourceState:
    """Return explicit unavailable evidence when a collector omits a source."""
    source = snapshot.sources.get(name)
    if source is not None:
        return source
    return SourceState(
        status="UNAVAILABLE",
        observed_at=snapshot.observed_at,
        detail=f"The {name} telemetry source was not reported by the collector.",
    )


def _normalized_readiness_gates(snapshot: StorageOverview) -> list[ReadinessGate]:
    gates = [gate.model_copy(deep=True) for gate in snapshot.readiness_gates]
    for gate in gates:
        required_sources = GATE_SOURCES.get(gate.id, ())
        states = [_source_state(snapshot, name).status for name in required_sources]
        if "UNAVAILABLE" in states and gate.state == "PASS":
            gate.state = "BLOCKED"
            gate.explanation = "Required telemetry source evidence is unavailable. " + gate.explanation
        elif "PARTIAL" in states and gate.state == "PASS":
            gate.state = "PARTIAL"
            gate.explanation = "Required telemetry source evidence is partial. " + gate.explanation
    return gates


@router_storage_dashboard.get("/overview", response_model=StorageOverview)
def storage_overview() -> StorageOverview:
    snapshot = get_snapshot()
    return snapshot.model_copy(update={
        "sources": {name: _source_state(snapshot, name) for name in EXPECTED_SOURCES},
        "readiness_gates": _normalized_readiness_gates(snapshot),
        "readiness_state": "NOT_VERIFIED",
    })


@router_storage_dashboard.get("/devices", response_model=DevicesResponse)
def storage_devices() -> DevicesResponse:
    snapshot = get_snapshot()
    return DevicesResponse(
        observed_at=snapshot.observed_at, freshness=snapshot.freshness,
        source=_source_state(snapshot, "mounts"), devices=snapshot.physical_devices,
    )


@router_storage_dashboard.get("/archive", response_model=ArchiveResponse)
def storage_archive() -> ArchiveResponse:
    snapshot = get_snapshot()
    return ArchiveResponse(
        observed_at=snapshot.observed_at, freshness=snapshot.freshness,
        source=_source_state(snapshot, "configuration"), archive=snapshot.archive_pool,
    )


@router_storage_dashboard.get("/backups", response_model=BackupsResponse)
def storage_backups() -> BackupsResponse:
    snapshot = get_snapshot()
    return BackupsResponse(
        observed_at=snapshot.observed_at, freshness=snapshot.freshness,
        source=_source_state(snapshot, "restic"), backups=snapshot.backups,
    )


@router_storage_dashboard.get("/health", response_model=HealthResponse)
def storage_health() -> HealthResponse:
    snapshot = get_snapshot()
    return HealthResponse(observed_at=snapshot.observed_at, freshness=snapshot.freshness, alerts=snapshot.alerts)


@router_storage_dashboard.get("/readiness", response_model=ReadinessResponse)
def storage_readiness() -> ReadinessResponse:
    snapshot = get_snapshot()
    return ReadinessResponse(
        observed_at=snapshot.observed_at, freshness=snapshot.freshness,
        overall="NOT_VERIFIED", gates=_normalized_readiness_gates(snapshot),
    )

