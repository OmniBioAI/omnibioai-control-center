"""Authenticated Storage Dashboard backed by read-only binds and a host snapshot.

The API process uses statvfs on configured collector bind points and never
accesses block devices, Restic credentials, or a Docker socket.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from control_center.api.storage_telemetry import (
    STALE_AFTER_SECONDS,
    load_targets,
    read_host_snapshot,
    snapshot_age_seconds,
)

router_storage_dashboard = APIRouter(prefix="/storage", tags=["storage-dashboard"])

CACHE_TTL_SECONDS = 15

SIGNED_METADATA_SOURCE = "Host storage telemetry snapshot"

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
    operational_state: str | None = None
    note: str | None = None


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


def _capacity(mount_point: str) -> tuple[int | None, int | None, int | None, float | None]:
    try:
        # A missing bind leaves an empty directory on the container's own root.
        if os.stat(mount_point).st_dev == os.stat("/").st_dev:
            return None, None, None, None
        statvfs = os.statvfs(mount_point)
        total = statvfs.f_blocks * statvfs.f_frsize
        available = statvfs.f_bavail * statvfs.f_frsize
        used = max(0, total - statvfs.f_bfree * statvfs.f_frsize)
        pct = round((used / total) * 100, 1) if total else None
        return total, used, available, pct
    except OSError:
        return None, None, None, None


def _archive_data(devices: list[DeviceVolume], fstab: dict[str, dict[str, object]]) -> ArchiveTelemetry:
    del fstab
    pool = next((device for device in devices if device.role == "archive"), None)
    return ArchiveTelemetry(
        pool_mount_point=pool.mount_point if pool else "Not configured",
        pool_status=pool.mount_status if pool else "UNKNOWN",
        total_bytes=pool.total_bytes if pool else None,
        used_bytes=pool.used_bytes if pool else None,
        available_bytes=pool.available_bytes if pool else None,
        utilization_percent=pool.utilization_percent if pool else None,
        branches=[], create_policy=None, min_free_bytes=None,
        min_free_policy_status="UNKNOWN", dependencies=[],
        dependency_assessment="NOT_VERIFIED", configured_source="control_center.yaml",
        dependency_note="Archive is configured as a single storage target.",
        runtime_policy_status="NOT_VERIFIED",
    )


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


def _health_alerts(devices: list[DeviceVolume], archive: ArchiveTelemetry, backups: BackupTelemetry, observed_at: str) -> list[HealthAlert]:
    alerts: list[HealthAlert] = []
    for device in devices:
        if device.mount_status == "MISSING":
            alerts.append(HealthAlert(
                id=f"mount-missing:{device.role}", state="ACTIVE", severity="CRITICAL",
                affected_device=device.label, source=SIGNED_METADATA_SOURCE,
                observed_at=observed_at, evidence=f"The collector reports {device.label} as missing.",
                suggested_action="Ask the host maintainer to verify the collector's mount observation before changing storage configuration.",
            ))
        elif device.health in {"WARNING", "CRITICAL"}:
            alerts.append(HealthAlert(
                id=f"capacity:{device.role}", state="ACTIVE", severity=device.health,
                affected_device=device.label, source=SIGNED_METADATA_SOURCE,
                observed_at=observed_at, evidence=device.health_detail,
                suggested_action=("Review available capacity and workload growth; do not delete data automatically." if "utilization" in device.health_detail else "Verify mount mode and host mount identity before changing configuration."),
            ))
    missing_branches = [branch for branch in archive.branches if branch.mount_status == "MISSING"]
    for branch in missing_branches:
        alerts.append(HealthAlert(
            id=f"archive-branch:{branch.role}", state="ACTIVE", severity="WARNING",
            affected_device=branch.role, source=SIGNED_METADATA_SOURCE,
            observed_at=observed_at, evidence="The collector reports this archive branch as missing.",
            suggested_action="Confirm the member mount and pool dependency behavior; preserve member contents.",
        ))
    if backups.repository_status == "UNAVAILABLE":
        alerts.append(HealthAlert(
            id="restic-unavailable", state="ACTIVE", severity="WARNING", affected_device=None,
            source="Restic telemetry unavailable", observed_at=observed_at, evidence=backups.detail,
            suggested_action="Keep repository telemetry unavailable until separate Restic access approval and validation.",
        ))
    return alerts


GATE_DEFINITIONS = (
    ("nvme-health", "Disk health", SIGNED_METADATA_SOURCE, "PARTIAL", "The host snapshot reports bounded SMART health and selected attributes."),
    ("device-identification", "Device identification", SIGNED_METADATA_SOURCE, "PARTIAL", "Configured roles are mapped to host devices by the root-owned collector configuration."),
    ("mount-integrity", "Mount verification", "Read-only target binds", "PARTIAL", "statvfs confirms readable collector binds; it does not prove filesystem integrity."),
    ("primary-reliability", "Primary disk reliability", SIGNED_METADATA_SOURCE, "PARTIAL", "SMART and filtered 24-hour kernel evidence are read from the host snapshot."),
    ("archive-integrity", "Archive filesystem integrity", "Filesystem health evidence", "NOT_VERIFIED", "A mounted filesystem is not proof of integrity."),
    ("mergerfs-resilience", "Archive resilience", SIGNED_METADATA_SOURCE, "NOT_VERIFIED", "Capacity and health telemetry do not prove failover or disconnect resilience."),
    ("restic-access", "Restic repository access", SIGNED_METADATA_SOURCE, "BLOCKED", "Restic repository status is supplied only by the host snapshot."),
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
        access.evidence_source = "Restic telemetry unavailable" if backups.repository_status == "UNAVAILABLE" else "Restic read-only snapshots command"
        inventory.evidence_source = "Restic telemetry unavailable" if backups.repository_status == "UNAVAILABLE" else "Restic snapshots JSON"
    return values


_cache_lock = threading.Lock()
_cache: tuple[float, StorageOverview] | None = None


def _collect() -> StorageOverview:
    targets = load_targets()
    host_snapshot, snapshot_error = read_host_snapshot()
    observed_at = host_snapshot.observed_at.isoformat() if host_snapshot else _now()
    age = snapshot_age_seconds(host_snapshot) if host_snapshot else None
    stale = age is not None and age > STALE_AFTER_SECONDS
    smart_by_role = {
        str(item.get("role")): item for item in (host_snapshot.smart if host_snapshot else [])
        if isinstance(item, dict) and item.get("role")
    }
    devices: list[DeviceVolume] = []
    alerts: list[HealthAlert] = []

    for target in targets:
        if not target.mount:
            devices.append(DeviceVolume(
                role=target.role, label=target.name, mount_point=target.host_path,
                mount_status="MISSING", mount_mode="UNKNOWN", health="UNKNOWN",
                health_detail="Not mounted", smart_status="UNKNOWN",
                operational_state=target.state,
                note="This target is being replaced." if target.state == "being_replaced" else None,
            ))
            continue
        mount_record = host_snapshot.mounts.get(target.role) if host_snapshot else None
        verified_mount = (
            isinstance(mount_record, dict) and mount_record.get("mounted") is True
            and mount_record.get("uuid") == target.expected_filesystem_uuid
        )
        total, used, available, percent = (
            _capacity(str(target.collector_path)) if verified_mount else (None, None, None, None)
        )
        mounted = verified_mount and total is not None
        smart = smart_by_role.get(target.role)
        attributes = smart.get("attributes", {}) if smart else {}
        failing = [number for number in ("5", "197", "198") if int(attributes.get(number, 0) or 0) > 0]
        crc_rise = bool(smart and smart.get("udma_crc_error_count_rise"))
        health: HealthState = "HEALTHY" if mounted else "UNKNOWN"
        detail = "Capacity collected with statvfs from the read-only bind mount" if mounted else (
            "Not mounted" if host_snapshot and (mount_record is None or not verified_mount or total is None)
            else f"No data: {snapshot_error or 'mount verification is missing'}"
        )
        if percent is not None and percent >= 95:
            health, detail = "CRITICAL", "Filesystem utilization is at least 95%"
        elif percent is not None and percent >= 85:
            health, detail = "WARNING", "Filesystem utilization is at least 85%"
        if not mounted:
            health = "UNKNOWN"
        if not smart or smart.get("error"):
            if health == "HEALTHY":
                health = "UNKNOWN"
                detail = f"No data: {snapshot_error or 'SMART observation is missing for this target'}"
        if failing:
            health = "WARNING"
            detail = f"SMART attributes {', '.join(failing)} report non-zero failing values"
        elif smart and smart.get("passed") is False:
            health, detail = "WARNING", "SMART overall-health assessment failed"
        note = "This target is being replaced." if target.state == "being_replaced" else None
        if crc_rise:
            cable_note = "SMART attribute 199 increased; check the cable or enclosure."
            note = f"{note} {cable_note}".strip() if note else cable_note
        device = DeviceVolume(
            role=target.role, label=target.name, mount_point=target.host_path,
            mount_status="MOUNTED" if mounted else "MISSING", mount_mode="READ_ONLY" if mounted else "UNKNOWN",
            total_bytes=total, used_bytes=used, available_bytes=available, utilization_percent=percent,
            smart_status="AVAILABLE" if smart and not smart.get("error") else "UNAVAILABLE",
            health=health, health_detail=detail, last_successful_observation=observed_at if mounted else None,
            last_observed_error=None if mounted else detail, operational_state=target.state, note=note,
        )
        devices.append(device)
        if health in {"WARNING", "CRITICAL"}:
            alerts.append(HealthAlert(
                id=f"storage:{target.role}", state="ACTIVE", severity=health,
                affected_device=target.name, source="statvfs/SMART snapshot", observed_at=observed_at,
                evidence=detail, suggested_action="Review the filesystem or disk health; no automatic action was taken.",
            ))

    restic = host_snapshot.restic if host_snapshot else {}
    snapshot_values = restic.get("snapshots", []) if isinstance(restic, dict) else []
    raw_snapshots = snapshot_values if isinstance(snapshot_values, list) else []
    snapshots, latest, truncated = parse_restic_snapshots(json.dumps(raw_snapshots))
    restic_error = restic.get("error") if isinstance(restic, dict) else None
    repository_available = host_snapshot is not None and not restic_error and isinstance(snapshot_values, list)
    stats = restic.get("stats") if isinstance(restic, dict) and isinstance(restic.get("stats"), dict) else {}
    stats_summary = ", ".join(f"{key.replace('_', ' ')}: {value}" for key, value in stats.items()) or None
    backups = BackupTelemetry(
        repository_status="AVAILABLE" if repository_available else "UNAVAILABLE",
        repository_id=restic.get("repository_id") if isinstance(restic, dict) else None,
        snapshot_count=len(raw_snapshots) if repository_available else None,
        snapshots_truncated=truncated, snapshots=snapshots, latest_snapshot_at=latest,
        schedule_status="UNKNOWN", schedules=[],
        retention_status="UNKNOWN", retention_summary=stats_summary, restore_verification="NOT_VERIFIED",
        observed_at=observed_at,
        detail="Restic inventory read from the host snapshot" if repository_available else f"No data: {restic_error or snapshot_error}",
    )
    if snapshots and max(item.age_seconds or 0 for item in snapshots) >= 0:
        latest_item = min((item for item in snapshots if item.age_seconds is not None), key=lambda item: item.age_seconds, default=None)
        if latest_item and latest_item.age_seconds is not None and latest_item.age_seconds > 7 * 86400:
            alerts.append(HealthAlert(
                id="restic:snapshot-old", state="ACTIVE", severity="WARNING", source="Restic snapshot",
                observed_at=observed_at, evidence="The latest Restic snapshot is older than 7 days.",
                suggested_action="Check the backup job and repository connectivity.",
            ))
    kernel = host_snapshot.kernel if host_snapshot else {}
    kernel_counts = kernel.get("counts") if isinstance(kernel.get("counts"), dict) else {}
    kernel_counts = {str(label): value for label, value in kernel_counts.items() if isinstance(value, int) and value > 0}
    if kernel_counts:
        kernel_devices = [str(name)[:32] for name in kernel.get("devices", [])[:16]] if isinstance(kernel.get("devices"), list) else []
        counts_text = ", ".join(f"{label.replace('_', ' ')}: {value}" for label, value in sorted(kernel_counts.items()))
        alerts.append(HealthAlert(
            id="kernel:storage-errors", state="ACTIVE", severity="WARNING", source="dmesg (last 24 hours)",
            affected_device=", ".join(kernel_devices) or None, observed_at=observed_at,
            evidence=f"Storage-related kernel messages in the last 24 hours ({counts_text}).",
            suggested_action="Review the host kernel log and affected disk or filesystem.",
        ))

    archive_device = next((item for item in devices if item.role == "archive"), None)
    archive = ArchiveTelemetry(
        pool_mount_point=archive_device.mount_point if archive_device else "Not configured",
        pool_status=archive_device.mount_status if archive_device else "UNKNOWN",
        total_bytes=archive_device.total_bytes if archive_device else None,
        used_bytes=archive_device.used_bytes if archive_device else None,
        available_bytes=archive_device.available_bytes if archive_device else None,
        utilization_percent=archive_device.utilization_percent if archive_device else None,
        branches=[], create_policy=None, min_free_bytes=None, min_free_policy_status="UNKNOWN",
        dependencies=[], dependency_assessment="NOT_VERIFIED", configured_source="control_center.yaml",
        dependency_note="Archive is configured as a single storage target.", runtime_policy_status="NOT_VERIFIED",
    )
    snapshot_detail = "Host snapshot is current" if host_snapshot and not stale else "Host snapshot is older than 2 hours" if stale else f"No data: {snapshot_error}"
    sources = {
        "mounts": SourceState(status="AVAILABLE" if targets else "UNAVAILABLE", observed_at=observed_at,
                              detail="Configured read-only bind mounts measured with statvfs" if targets else "No storage targets configured"),
        "configuration": SourceState(status="AVAILABLE" if targets else "UNAVAILABLE", observed_at=observed_at,
                                     detail="Storage targets loaded from control_center.yaml" if targets else "No storage targets configured"),
        "smart": SourceState(status="AVAILABLE" if host_snapshot and host_snapshot.smart else "UNAVAILABLE", observed_at=observed_at, detail=snapshot_detail),
        "restic": SourceState(status=backups.repository_status, observed_at=observed_at, detail=backups.detail),
        "docker": SourceState(status="UNAVAILABLE", observed_at=observed_at, detail="Docker socket is intentionally not mounted"),
    }
    return StorageOverview(
        observed_at=observed_at, freshness="STALE" if stale else "CURRENT" if host_snapshot else "UNKNOWN", sources=sources,
        physical_devices=devices, archive_pool=archive,
        backups=backups, alerts=alerts, readiness_gates=_readiness(observed_at, backups),
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
                return _cache[1].model_copy(update={"freshness": "STALE"})
            observed_at = _now()
            configured_targets = load_targets()
            unavailable_devices = [DeviceVolume(
                role=target.role, label=target.name, mount_point=target.host_path,
                mount_status="UNKNOWN", mount_mode="UNKNOWN", health="UNKNOWN",
                health_detail="Collector failed before this source could be observed",
                operational_state=target.state,
            ) for target in configured_targets]
            archive_target = next((target for target in configured_targets if target.role == "archive"), None)
            unavailable_archive = ArchiveTelemetry(
                pool_mount_point=archive_target.host_path if archive_target else "Not configured", pool_status="UNKNOWN", branches=[],
                create_policy=None, min_free_bytes=None, min_free_policy_status="UNKNOWN",
                dependencies=[], dependency_assessment="NOT_VERIFIED",
                configured_source="Unavailable", dependency_note="Collector failed; dependencies were not observed.",
                runtime_policy_status="NOT_VERIFIED",
            )
            unavailable_backups = BackupTelemetry(
                repository_status="UNAVAILABLE", snapshots=[], schedule_status="UNKNOWN", schedules=[],
                retention_status="UNKNOWN", restore_verification="NOT_VERIFIED", observed_at=observed_at,
                detail="No data: collector failed before the host snapshot could be read.",
            )
            return StorageOverview(
                observed_at=observed_at, freshness="UNKNOWN",
                sources={name: SourceState(status="UNAVAILABLE", observed_at=observed_at, detail="Collector failed; telemetry unavailable")
                         for name in ("mounts", "configuration", "smart", "restic", "docker")},
                physical_devices=unavailable_devices,
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

