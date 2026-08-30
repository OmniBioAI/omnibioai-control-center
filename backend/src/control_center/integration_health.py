"""Pure Integration Health V1 contract.

This module deliberately models supplied evidence; it does not discover
plugins, read environment variables, call providers, or inspect Docker.  A
future adapter may translate Workbench registry/configuration/probe records
into these types.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class _ValueEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class ImplementationStatus(_ValueEnum):
    IMPLEMENTED = "IMPLEMENTED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class EnabledStatus(_ValueEnum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    UNKNOWN = "UNKNOWN"


class ConfigurationStatus(_ValueEnum):
    CONFIGURED = "CONFIGURED"
    PARTIAL = "PARTIAL"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    NOT_REQUIRED = "NOT_REQUIRED"
    UNKNOWN = "UNKNOWN"


class ProviderStatus(_ValueEnum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"
    NOT_CHECKED = "NOT_CHECKED"


class ReadinessStatus(_ValueEnum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    NOT_READY = "NOT_READY"
    DISABLED = "DISABLED"
    UNKNOWN = "UNKNOWN"


class Freshness(_ValueEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class AuthRequirement(_ValueEnum):
    PUBLIC = "PUBLIC"
    OPTIONAL_AUTH = "OPTIONAL_AUTH"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    UNKNOWN = "UNKNOWN"


class EvidenceType(_ValueEnum):
    PLUGIN_REGISTRY = "PLUGIN_REGISTRY"
    PLUGIN_CONFIGURATION = "PLUGIN_CONFIGURATION"
    PLUGIN_TEST = "PLUGIN_TEST"
    LIVE_PROBE = "LIVE_PROBE"
    REGRESSION_CERTIFICATION = "REGRESSION_CERTIFICATION"
    PROVIDER_METADATA = "PROVIDER_METADATA"
    CACHED_SUCCESS = "CACHED_SUCCESS"
    CONFIGURATION = "CONFIGURATION"


class FailureReason(_ValueEnum):
    NETWORK = "NETWORK"
    TIMEOUT = "TIMEOUT"
    DNS = "DNS"
    AUTHENTICATION = "AUTHENTICATION"
    AUTHORIZATION = "AUTHORIZATION"
    RATE_LIMIT = "RATE_LIMIT"
    PROVIDER_5XX = "PROVIDER_5XX"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    CONFIGURATION = "CONFIGURATION"
    DISABLED = "DISABLED"
    UNKNOWN = "UNKNOWN"


class ProbeAvailability(_ValueEnum):
    READY_SIGNAL_EXISTS = "READY_SIGNAL_EXISTS"
    PLUGIN_LIVENESS_ONLY = "PLUGIN_LIVENESS_ONLY"
    NEEDS_SMALL_READ_ONLY_PROBE = "NEEDS_SMALL_READ_ONLY_PROBE"
    NO_SAFE_READINESS_SIGNAL = "NO_SAFE_READINESS_SIGNAL"


class DataSourceStatus(_ValueEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


_ABSOLUTE_PATH = re.compile(r"(?:^|\s)(?:/|[A-Za-z]:[\\/])[^\s]*")
_TOKEN_LIKE = re.compile(r"(?i)\b(?:bearer\s+|eyJ[a-z0-9_-]{8,}|(?:api[_ -]?key|token|secret)\s*[:=]\s*)\S+")


def _safe_text(value: str) -> str:
    """Keep evidence useful while preventing common secret/path leakage."""
    text = str(value)
    text = _TOKEN_LIKE.sub("[REDACTED]", text)
    text = _ABSOLUTE_PATH.sub("[REDACTED_PATH]", text)
    return text[:500]


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def freshness_for(last_checked: datetime | None, *, now: datetime, stale_after_seconds: int) -> Freshness:
    if last_checked is None:
        return Freshness.UNKNOWN
    checked = last_checked if last_checked.tzinfo else last_checked.replace(tzinfo=UTC)
    current = now if now.tzinfo else now.replace(tzinfo=UTC)
    age = (current - checked.astimezone(UTC)).total_seconds()
    return Freshness.STALE if age > stale_after_seconds else Freshness.CURRENT


@dataclass(frozen=True)
class IntegrationEvidence:
    source: EvidenceType
    status: str
    description: str
    timestamp: datetime | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.value,
            "status": _safe_text(self.status),
            "description": _safe_text(self.description),
            "timestamp": _iso(self.timestamp),
        }


@dataclass(frozen=True)
class IntegrationProvider:
    name: str
    api_type: str
    endpoint_family: str | None = None
    status: ProviderStatus = ProviderStatus.NOT_CHECKED
    last_checked: datetime | None = None
    failure_reason: FailureReason | None = None
    version: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.api_type.strip():
            raise ValueError("provider name and api_type are required")
        if self.failure_reason is not None and self.status not in {
            ProviderStatus.DEGRADED, ProviderStatus.UNAVAILABLE
        }:
            raise ValueError("failure_reason requires a degraded or unavailable provider")

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "name": _safe_text(self.name),
            "api_type": _safe_text(self.api_type),
            "endpoint_family": _safe_text(self.endpoint_family) if self.endpoint_family else None,
            "status": self.status.value,
            "last_checked": _iso(self.last_checked),
            "failure_reason": self.failure_reason.value if self.failure_reason else None,
            "version": _safe_text(self.version) if self.version else None,
        }


@dataclass(frozen=True)
class IntegrationRecord:
    integration_id: str
    display_name: str
    provider: IntegrationProvider
    category: str
    plugin: str
    implementation_status: ImplementationStatus = ImplementationStatus.IMPLEMENTED
    enabled_status: EnabledStatus = EnabledStatus.UNKNOWN
    configuration_status: ConfigurationStatus = ConfigurationStatus.UNKNOWN
    auth_requirement: AuthRequirement = AuthRequirement.UNKNOWN
    credential_configured: bool | None = None
    probe_availability: ProbeAvailability = ProbeAvailability.NO_SAFE_READINESS_SIGNAL
    plugin_status: str = "UNKNOWN"
    evidence: tuple[IntegrationEvidence, ...] = field(default_factory=tuple)
    test_status: str = "UNKNOWN"
    certification_status: str = "UNKNOWN"
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def readiness(self) -> ReadinessStatus:
        if self.enabled_status is EnabledStatus.DISABLED:
            return ReadinessStatus.DISABLED
        if self.implementation_status is ImplementationStatus.NOT_IMPLEMENTED:
            return ReadinessStatus.NOT_READY
        if self.enabled_status is not EnabledStatus.ENABLED:
            return ReadinessStatus.UNKNOWN
        if self.auth_requirement is AuthRequirement.AUTH_REQUIRED and self.credential_configured is not True:
            return ReadinessStatus.NOT_READY
        if self.configuration_status in {ConfigurationStatus.NOT_CONFIGURED, ConfigurationStatus.PARTIAL}:
            return ReadinessStatus.NOT_READY
        if self.provider.status is ProviderStatus.AVAILABLE:
            return ReadinessStatus.READY
        if self.provider.status is ProviderStatus.DEGRADED:
            return ReadinessStatus.DEGRADED
        if self.provider.status is ProviderStatus.UNAVAILABLE:
            return ReadinessStatus.NOT_READY
        if self.configuration_status is ConfigurationStatus.UNKNOWN:
            return ReadinessStatus.UNKNOWN
        return ReadinessStatus.UNKNOWN

    def to_public_dict(self, *, now: datetime, stale_after_seconds: int = 3600) -> dict[str, Any]:
        return {
            "integration_id": _safe_text(self.integration_id),
            "display_name": _safe_text(self.display_name),
            "provider": self.provider.to_public_dict(),
            "category": _safe_text(self.category),
            "plugin": _safe_text(self.plugin),
            "implementation_status": self.implementation_status.value,
            "enabled_status": self.enabled_status.value,
            "configuration_status": self.configuration_status.value,
            "authentication": {
                "requirement": self.auth_requirement.value,
                "credential_configured": self.credential_configured,
            },
            "plugin_status": _safe_text(self.plugin_status),
            "readiness_status": self.readiness().value,
            "freshness": freshness_for(self.provider.last_checked, now=now, stale_after_seconds=stale_after_seconds).value,
            "health_signal_capability": self.probe_availability.value,
            "version": _safe_text(self.provider.version) if self.provider.version else None,
            "test_status": _safe_text(self.test_status),
            "certification_status": _safe_text(self.certification_status),
            "evidence": [item.to_public_dict() for item in self.evidence],
            "warnings": [_safe_text(item) for item in self.warnings],
        }


@dataclass(frozen=True)
class IntegrationSummary:
    total: int
    ready: int
    degraded: int
    not_ready: int
    disabled: int
    unknown: int

    @classmethod
    def from_records(cls, records: Iterable[IntegrationRecord]) -> IntegrationSummary:
        counts = {status: 0 for status in ReadinessStatus}
        for record in records:
            counts[record.readiness()] += 1
        return cls(
            total=sum(counts.values()), ready=counts[ReadinessStatus.READY],
            degraded=counts[ReadinessStatus.DEGRADED], not_ready=counts[ReadinessStatus.NOT_READY],
            disabled=counts[ReadinessStatus.DISABLED], unknown=counts[ReadinessStatus.UNKNOWN],
        )

    def to_public_dict(self) -> dict[str, int]:
        return {"total": self.total, "ready": self.ready, "degraded": self.degraded,
                "not_ready": self.not_ready, "disabled": self.disabled, "unknown": self.unknown}


@dataclass(frozen=True)
class IntegrationInventory:
    records: tuple[IntegrationRecord, ...]
    data_sources: dict[str, DataSourceStatus] = field(default_factory=dict)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def summary(self) -> IntegrationSummary:
        return IntegrationSummary.from_records(self.records)

    def to_public_dict(self, *, generated_at: datetime, stale_after_seconds: int = 3600) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "generated_at": _iso(generated_at),
            "summary": self.summary().to_public_dict(),
            "integrations": [r.to_public_dict(now=generated_at, stale_after_seconds=stale_after_seconds)
                             for r in self.records],
            "data_sources": {key: value.value for key, value in sorted(self.data_sources.items())},
            "warnings": [_safe_text(item) for item in self.warnings],
        }
