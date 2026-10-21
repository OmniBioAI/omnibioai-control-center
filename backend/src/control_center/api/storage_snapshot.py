"""Authenticated reader for the host's metadata-only storage snapshot."""
from __future__ import annotations

import base64
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError

SNAPSHOT_PATH = Path("/run/storage-telemetry/snapshot.json")
MAX_SNAPSHOT_BYTES = 64 * 1024
MAX_AGE_SECONDS = 120
MAX_FUTURE_SECONDS = 30
ROLES = {
    "compute", "primary", "backup", "archive-writable",
    "archive-member-a", "archive-member-b", "archive-pool",
}
EXPECTED_FILESYSTEMS = {
    "compute": {"ext4"}, "primary": {"ext4"}, "backup": {"ext4"},
    "archive-writable": {"ext4"}, "archive-member-a": {"ext4"},
    "archive-member-b": {"exfat"}, "archive-pool": {"fuse.mergerfs"},
}


class Metric(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["AVAILABLE", "MISSING", "INVALID"]
    filesystem: str | None = Field(max_length=32)
    device_fingerprint: str | None = Field(pattern=r"^[a-f0-9]{64}$")
    mount_mode: Literal["READ_ONLY", "READ_WRITE", "UNKNOWN"]
    expected_mode: Literal["READ_ONLY", "READ_WRITE", "UNKNOWN"]
    total_bytes: int | None = Field(ge=0)
    used_bytes: int | None = Field(ge=0)
    available_bytes: int | None = Field(ge=0)


class ArchivePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    create_policy: str | None = Field(max_length=32)
    min_free_bytes: int | None = Field(ge=0)
    min_free_policy_status: Literal["CONFIGURED", "NOT_CONFIGURED", "UNKNOWN"]
    dependency_count: int = Field(ge=0, le=32)


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1]
    observed_at: datetime
    collector_status: Literal["AVAILABLE", "PARTIAL", "UNAVAILABLE"]
    metrics: dict[str, Metric]
    archive_complete: bool
    archive_policy: ArchivePolicy


def read_snapshot(path: Path = SNAPSHOT_PATH, *, public_key: str | None = None,
                  now: datetime | None = None) -> Payload | None:
    """Return trusted, fresh metrics. Any filesystem, integrity, or schema error fails closed."""
    try:
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode)
                or before.st_nlink != 1 or before.st_uid not in {0, os.geteuid()}
                or before.st_mode & 0o222 or before.st_size > MAX_SNAPSHOT_BYTES):
            return None
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
        try:
            opened = os.fstat(fd)
            if (opened.st_ino != before.st_ino or opened.st_dev != before.st_dev
                    or not stat.S_ISREG(opened.st_mode) or opened.st_size > MAX_SNAPSHOT_BYTES):
                return None
            chunks = bytearray()
            while len(chunks) <= MAX_SNAPSHOT_BYTES:
                part = os.read(fd, min(8192, MAX_SNAPSHOT_BYTES + 1 - len(chunks)))
                if not part:
                    break
                chunks.extend(part)
            if len(chunks) > MAX_SNAPSHOT_BYTES:
                return None
        finally:
            os.close(fd)
        envelope = json.loads(chunks)
        if not isinstance(envelope, dict) or set(envelope) != {"payload", "signature"}:
            return None
        payload_raw = envelope["payload"]
        canonical = json.dumps(payload_raw, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        key_text = public_key if public_key is not None else os.environ.get("STORAGE_TELEMETRY_PUBLIC_KEY", "")
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(key_text, validate=True))
        key.verify(base64.b64decode(envelope["signature"], validate=True), canonical)
        payload = Payload.model_validate_json(json.dumps(payload_raw, separators=(",", ":")))
        if set(payload.metrics) != ROLES:
            return None
        metric_states = {metric.status for metric in payload.metrics.values()}
        expected_state = "AVAILABLE" if metric_states == {"AVAILABLE"} else "PARTIAL" if "AVAILABLE" in metric_states else "UNAVAILABLE"
        if payload.collector_status != expected_state:
            return None
        observed = payload.observed_at
        if observed.tzinfo is None:
            return None
        age = ((now or datetime.now(timezone.utc)) - observed.astimezone(timezone.utc)).total_seconds()
        if age > MAX_AGE_SECONDS or age < -MAX_FUTURE_SECONDS:
            return None
        if payload.archive_complete:
            for role in ("archive-writable", "archive-member-a", "archive-member-b", "archive-pool"):
                if payload.metrics[role].status != "AVAILABLE":
                    return None
            if any(payload.metrics[role].expected_mode == "UNKNOWN" for role in ("archive-writable", "archive-member-a", "archive-member-b")):
                return None
            if payload.metrics["archive-pool"].filesystem != "fuse.mergerfs":
                return None
        elif payload.metrics["archive-pool"].status == "AVAILABLE":
            return None
        for role, metric in payload.metrics.items():
            if metric.status != "AVAILABLE":
                if any(v is not None for v in (metric.total_bytes, metric.used_bytes, metric.available_bytes)):
                    return None
            elif (metric.filesystem is None or metric.device_fingerprint is None
                  or metric.total_bytes is None or metric.used_bytes is None or metric.available_bytes is None
                  or metric.used_bytes + metric.available_bytes > metric.total_bytes
                  or metric.filesystem not in EXPECTED_FILESYSTEMS[role]
                  or metric.mount_mode == "UNKNOWN"):
                return None
        return payload
    except (OSError, ValueError, TypeError, KeyError, ValidationError, json.JSONDecodeError,
            UnicodeDecodeError, OverflowError):
        return None
    except Exception:
        # Invalid signatures and cryptographic parsing errors are deliberately indistinguishable.
        return None
