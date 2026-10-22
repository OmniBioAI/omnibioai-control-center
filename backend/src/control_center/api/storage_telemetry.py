"""Read-only storage target and host snapshot collection.

The API only calls statvfs on explicitly configured read-only bind mounts and
reads the host-generated JSON snapshot. It never invokes smartctl or restic.
"""
from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
STALE_AFTER_SECONDS = 2 * 60 * 60
SNAPSHOT_PATH = Path(os.environ.get("STORAGE_TELEMETRY_PATH", "/run/storage-telemetry/storage-telemetry.json"))


class StorageTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    role: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    host_path: str = Field(pattern=r"^/")
    expected_filesystem_uuid: str = Field(min_length=1, max_length=80)
    mount: bool = True
    state: str | None = None

    @property
    def collector_path(self) -> Path:
        return Path("/run/storage-targets") / self.role


class HostSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: int
    observed_at: datetime
    smart: list[dict[str, Any]] = Field(default_factory=list)
    mounts: dict[str, dict[str, Any]] = Field(default_factory=dict)
    kernel: dict[str, Any] = Field(default_factory=dict)
    restic: dict[str, Any] = Field(default_factory=dict)

    @field_validator("schema_version")
    @classmethod
    def supported_schema(cls, value: int) -> int:
        if value != 1:
            raise ValueError("unsupported storage telemetry schema")
        return value


def load_targets(config_path: Path | None = None) -> list[StorageTarget]:
    path = config_path or Path(os.environ.get("CONTROL_CENTER_CONFIG", "/config/control_center.yaml"))
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(document, dict):
            return []
        system = document.get("system", {})
        if not isinstance(system, dict):
            return []
        values = system.get("storage_targets", [])
        if not isinstance(values, list):
            return []
        targets = [StorageTarget.model_validate(item) for item in values]
        roles = [item.role for item in targets]
        if len(set(roles)) != len(roles):
            return []
        return targets
    except (OSError, TypeError, AttributeError, ValidationError, yaml.YAMLError):
        return []


def read_host_snapshot(path: Path | None = None) -> tuple[HostSnapshot | None, str | None]:
    source = path or SNAPSHOT_PATH
    try:
        details = source.lstat()
        if (not stat.S_ISREG(details.st_mode) or stat.S_ISLNK(details.st_mode)
                or details.st_size > MAX_SNAPSHOT_BYTES or details.st_uid != 0
                or stat.S_IMODE(details.st_mode) != 0o644):
            return None, "snapshot file is not a safe regular file"
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(source, flags)
        try:
            opened = os.fstat(descriptor)
            if (opened.st_dev != details.st_dev or opened.st_ino != details.st_ino
                    or not stat.S_ISREG(opened.st_mode) or opened.st_uid != 0
                    or stat.S_IMODE(opened.st_mode) != 0o644 or opened.st_size > MAX_SNAPSHOT_BYTES):
                return None, "snapshot file changed while opening"
            chunks = bytearray()
            while len(chunks) <= MAX_SNAPSHOT_BYTES:
                part = os.read(descriptor, min(8192, MAX_SNAPSHOT_BYTES + 1 - len(chunks)))
                if not part:
                    break
                chunks.extend(part)
            raw = bytes(chunks)
        finally:
            os.close(descriptor)
        if len(raw) > MAX_SNAPSHOT_BYTES:
            return None, "snapshot file exceeds the size limit"
        snapshot = HostSnapshot.model_validate_json(raw)
        if snapshot.observed_at.tzinfo is None:
            return None, "snapshot timestamp has no timezone"
        return snapshot, None
    except FileNotFoundError:
        return None, "snapshot file is missing"
    except PermissionError:
        return None, "snapshot file is not readable"
    except (OSError, ValidationError, ValueError, json.JSONDecodeError):
        return None, "snapshot file is invalid"


def snapshot_age_seconds(snapshot: HostSnapshot, now: datetime | None = None) -> int:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return max(0, int((moment - snapshot.observed_at.astimezone(timezone.utc)).total_seconds()))
