"""IH-3 bounded P0 provider probes.

This module is an internal, injectable runner.  It is intentionally not
called by GET /integration-health.  Destinations are static code-owned
definitions; no URL, host, query, concurrency, or retry setting is accepted
from a caller.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, Protocol

import httpx
from control_center.integration_health import (
    AuthRequirement,
    FailureReason,
    ProviderStatus,
    ReadinessStatus,
)

log = logging.getLogger(__name__)

MAX_WORKERS = 4
DEFAULT_TIMEOUT_SECONDS = 5.0
MAX_RESPONSE_BYTES = 64 * 1024


@dataclass(frozen=True)
class ProbeDefinition:
    integration_id: str
    provider_id: str
    probe_type: str
    endpoint: str
    auth_requirement: AuthRequirement
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    cooldown_seconds: int = 300


# These are fixed public endpoints with bounded, non-scientific responses.
# gnomAD/Open Targets/STRING health clients use GraphQL or POST and are kept
# out of this GET-only allowlist until a separate safe contract is approved.
P0_PROBE_DEFINITIONS: tuple[ProbeDefinition, ...] = (
    ProbeDefinition("ncbi", "ncbi", "GET_EINFO", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi?db=gene&retmode=json", AuthRequirement.OPTIONAL_AUTH),
    ProbeDefinition("pubchem", "pubchem", "GET_COMPOUND_PROPERTY", "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/2244/property/MolecularFormula/JSON", AuthRequirement.PUBLIC),
    ProbeDefinition("ensembl", "ensembl", "GET_PING", "https://rest.ensembl.org/info/ping", AuthRequirement.PUBLIC),
    ProbeDefinition("clinvar", "clinvar", "GET_EINFO", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi?db=clinvar&retmode=json", AuthRequirement.OPTIONAL_AUTH),
    ProbeDefinition("uniprot", "uniprot", "GET_ENTRY", "https://rest.uniprot.org/uniprotkb/P04637.json", AuthRequirement.PUBLIC),
    ProbeDefinition("reactome", "reactome", "GET_VERSION", "https://reactome.org/ContentService/data/database/version", AuthRequirement.PUBLIC),
    ProbeDefinition("rcsb_pdb", "rcsb_pdb", "GET_ENTRY", "https://data.rcsb.org/rest/v1/core/entry/4HHB", AuthRequirement.PUBLIC),
)

P0_UNSUPPORTED: dict[str, str] = {
    "gnomad": "existing health contract uses GraphQL POST; no approved GET probe",
    "opentargets": "existing health contract uses GraphQL POST; no approved GET probe",
    "string_db": "existing health contract uses POST/version API; no approved GET probe",
}


@dataclass(frozen=True)
class ProbeResponse:
    status_code: int
    headers: dict[str, str]
    payload: Any


class ProbeTransport(Protocol):
    def get(self, definition: ProbeDefinition) -> ProbeResponse: ...


class HttpxProbeTransport:
    """Static-definition-only HTTP transport with no redirects."""

    def get(self, definition: ProbeDefinition) -> ProbeResponse:
        timeout = httpx.Timeout(definition.timeout_seconds)
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            response = client.get(definition.endpoint)
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise ValueError("response_too_large")
        content_type = response.headers.get("content-type", "").lower()
        if "json" in content_type:
            try:
                payload: Any = response.json()
            except ValueError:
                payload = None
        else:
            payload = response.text[:2048]
        return ProbeResponse(response.status_code, dict(response.headers), payload)


class ProbeCache(Protocol):
    def get(self, integration_id: str) -> dict[str, Any] | None: ...
    def set(self, integration_id: str, result: dict[str, Any]) -> None: ...


class JsonProbeCache:
    """Small normalized JSON cache with atomic writes and no secret fields."""

    _allowed: ClassVar = {"provider_status", "checked_at", "next_eligible_at", "failure_reason", "version", "description"}

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        try:
            self._data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, json.JSONDecodeError):
            self._data = {}
        if not isinstance(self._data, dict):
            self._data = {}

    def get(self, integration_id: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._data.get(integration_id)
            return dict(value) if isinstance(value, dict) else None

    def set(self, integration_id: str, result: dict[str, Any]) -> None:
        safe = {key: value for key, value in result.items() if key in self._allowed}
        with self._lock:
            self._data[integration_id] = safe
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix="integration-health-", suffix=".json", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(self._data, handle, sort_keys=True)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_name, self.path)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)


@dataclass(frozen=True)
class ProbeResult:
    integration_id: str
    provider_status: ProviderStatus
    readiness_status: ReadinessStatus
    failure_reason: FailureReason | None
    checked_at: datetime
    duration_ms: int
    description: str
    retry_after_seconds: int | None = None

    def to_cache_dict(self) -> dict[str, Any]:
        result = {
            "provider_status": self.provider_status.value,
            "checked_at": self.checked_at.isoformat().replace("+00:00", "Z"),
            "failure_reason": self.failure_reason.value if self.failure_reason else None,
            "description": self.description,
        }
        if self.retry_after_seconds is not None:
            result["next_eligible_at"] = datetime.fromtimestamp(
                self.checked_at.timestamp() + self.retry_after_seconds, tz=UTC
            ).isoformat().replace("+00:00", "Z")
        return result


@dataclass(frozen=True)
class ProbeRunSummary:
    results: tuple[ProbeResult, ...]
    skipped_cooldown: tuple[str, ...] = ()
    unsupported: tuple[str, ...] = ()


def _retry_after(headers: dict[str, str]) -> int | None:
    value = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return max(0, int(float(value))) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_cached_time(value: Any) -> datetime:
    text = str(value)
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    return datetime.fromisoformat(normalized)


def _success(definition: ProbeDefinition, payload: Any) -> bool:
    if definition.integration_id in {"ncbi", "clinvar"}:
        return isinstance(payload, dict) and isinstance(payload.get("header"), dict)
    if definition.integration_id == "pubchem":
        return isinstance(payload, dict) and isinstance(payload.get("PropertyTable"), dict)
    if definition.integration_id == "ensembl":
        return isinstance(payload, dict) and "ping" in payload
    if definition.integration_id == "uniprot":
        return isinstance(payload, dict) and isinstance(payload.get("primaryAccession"), str)
    if definition.integration_id == "rcsb_pdb":
        return isinstance(payload, dict) and isinstance(payload.get("rcsb_id"), str)
    if definition.integration_id == "reactome":
        return isinstance(payload, str) and bool(payload.strip())
    return False


def _probe_one(definition: ProbeDefinition, transport: ProbeTransport, now: datetime) -> ProbeResult:
    started = time.monotonic()
    try:
        response = transport.get(definition)
        duration_ms = int((time.monotonic() - started) * 1000)
        if response.status_code == 429:
            retry_after = _retry_after(response.headers)
            return ProbeResult(definition.integration_id, ProviderStatus.DEGRADED, ReadinessStatus.DEGRADED,
                               FailureReason.RATE_LIMIT, now, duration_ms, "Provider rate limited the probe",
                               retry_after)
        if response.status_code in {401, 403}:
            reason = FailureReason.AUTHENTICATION if response.status_code == 401 else FailureReason.AUTHORIZATION
            return ProbeResult(definition.integration_id, ProviderStatus.UNAVAILABLE, ReadinessStatus.NOT_READY,
                               reason, now, duration_ms, "Provider rejected the probe")
        if response.status_code >= 500:
            return ProbeResult(definition.integration_id, ProviderStatus.UNAVAILABLE, ReadinessStatus.NOT_READY,
                               FailureReason.PROVIDER_5XX, now, duration_ms, "Provider returned a server error")
        if not 200 <= response.status_code < 300:
            return ProbeResult(definition.integration_id, ProviderStatus.UNAVAILABLE, ReadinessStatus.NOT_READY,
                               FailureReason.INVALID_RESPONSE, now, duration_ms, "Provider returned an unexpected status")
        if not _success(definition, response.payload):
            return ProbeResult(definition.integration_id, ProviderStatus.UNAVAILABLE, ReadinessStatus.NOT_READY,
                               FailureReason.SCHEMA_MISMATCH, now, duration_ms, "Provider response schema was not recognized")
        return ProbeResult(definition.integration_id, ProviderStatus.AVAILABLE, ReadinessStatus.READY,
                           None, now, duration_ms, "Bounded provider readiness probe succeeded")
    except httpx.TimeoutException:
        reason = FailureReason.TIMEOUT
    except httpx.ConnectError:
        reason = FailureReason.DNS
    except (httpx.NetworkError, OSError):
        reason = FailureReason.NETWORK
    except ValueError:
        reason = FailureReason.INVALID_RESPONSE
    duration_ms = int((time.monotonic() - started) * 1000)
    return ProbeResult(definition.integration_id, ProviderStatus.UNAVAILABLE, ReadinessStatus.NOT_READY,
                       reason, now, duration_ms, "Provider probe failed with a normalized error")


class P0ProbeRunner:
    """Bounded internal runner. It is never invoked by the GET route."""

    def __init__(self, *, transport: ProbeTransport | None = None, cache: ProbeCache | None = None,
                 definitions: tuple[ProbeDefinition, ...] = P0_PROBE_DEFINITIONS,
                 max_workers: int = MAX_WORKERS) -> None:
        self.transport = transport or HttpxProbeTransport()
        self.cache = cache
        self.definitions = definitions
        self.max_workers = min(MAX_WORKERS, max(1, max_workers))

    def run(self, *, now: datetime | None = None) -> ProbeRunSummary:
        checked_at = now or datetime.now(UTC)
        results: list[ProbeResult] = []
        skipped: list[str] = []
        eligible: list[ProbeDefinition] = []
        for definition in self.definitions:
            if definition.integration_id in P0_UNSUPPORTED:
                continue
            cached = self.cache.get(definition.integration_id) if self.cache else None
            if cached and cached.get("checked_at"):
                try:
                    checked = _parse_cached_time(cached["checked_at"])
                    next_eligible = _parse_cached_time(cached["next_eligible_at"]) if cached.get("next_eligible_at") else checked
                    cooldown_until = max(
                        checked.timestamp() + definition.cooldown_seconds,
                        next_eligible.timestamp(),
                    )
                    if checked_at.timestamp() < cooldown_until:
                        skipped.append(definition.integration_id)
                        continue
                except ValueError:
                    pass
            eligible.append(definition)
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(_probe_one, definition, self.transport, checked_at): definition for definition in eligible}
            for future in as_completed(futures):
                definition = futures[future]
                try:
                    result = future.result()
                except Exception:  # isolate an unexpected provider adapter failure
                    log.exception("Integration probe failed: %s", definition.integration_id)
                    result = ProbeResult(definition.integration_id, ProviderStatus.UNKNOWN, ReadinessStatus.UNKNOWN,
                                         FailureReason.UNKNOWN, checked_at, 0, "Provider probe failed safely")
                results.append(result)
                if self.cache:
                    self.cache.set(result.integration_id, result.to_cache_dict())
                log.info("integration_probe id=%s status=%s failure=%s duration_ms=%s",
                         result.integration_id, result.provider_status.value,
                         result.failure_reason.value if result.failure_reason else None, result.duration_ms)
        return ProbeRunSummary(tuple(sorted(results, key=lambda result: result.integration_id)), tuple(sorted(skipped)),
                               tuple(sorted(P0_UNSUPPORTED)))
