"""DH-2: read-only runtime merge, health computation, and response shaping
for Deployment Health.

Every function in this module is pure -- it takes already-fetched data
(a DH-1 `DeploymentInventory`, a Docker container list, application-probe
results, Prometheus/Regression Health context) and returns a plain dict
response body. None of it performs I/O itself; `api/routes_deployment_health.py`
does the I/O (reusing existing Control Center functions, never a second
Docker/probe implementation) and passes the results in here. This keeps the
logic-heavy code testable without Docker, network, or FastAPI.

## Intrinsic vs. effective health

Every service gets two health values:

- **Intrinsic**: what the service's own evidence says, independent of any
  dependency. Precedence, verified against this repo's actual architecture
  rather than assumed: `core.runner.run_all_checks` (the existing
  application-probe layer, keyed by the same service_id as Compose) beats
  Docker's built-in healthcheck state, which beats bare "container is
  running" (which is evidence of nothing about service health --
  CONTAINER RUNNING != SERVICE HEALTHY), which beats UNKNOWN.
- **Effective**: intrinsic health adjusted for HARD dependency evidence
  only. SOFT dependency failures never change it. `UNHEALTHY` is reserved
  exclusively for intrinsic failure -- a dependency problem can push a
  service to `DEGRADED` at most, never `UNHEALTHY` (mirrors the brief's
  own TES/ToolServer example, generalized as an explicit invariant).

## Dependency propagation is exactly one hop

Effective health for service A only ever looks at A's own intrinsic health
and the *intrinsic* (never effective) health of A's direct dependencies.
It never walks a dependency's dependencies. This isn't a simplification
that risks missing something -- it's what makes the computation cycle-safe
and O(services + edges) by construction: with no multi-hop traversal, a
dependency cycle cannot cause recursion or a status explosion, because
there is no recursion to begin with.

## Propagation table

1. intrinsic UNHEALTHY -> effective UNHEALTHY (dependencies irrelevant)
2. intrinsic UNKNOWN, no HARD dependency UNHEALTHY -> effective UNKNOWN
3. intrinsic UNKNOWN, some HARD dependency UNHEALTHY -> effective DEGRADED
   (a confirmed-unhealthy hard dependency is stronger evidence than no
   evidence at all, even though this service's own state is unproven)
4. intrinsic HEALTHY/DEGRADED, some HARD dependency UNHEALTHY -> DEGRADED
5. intrinsic HEALTHY/DEGRADED, no HARD dep UNHEALTHY but some HARD dep
   UNKNOWN -> DEGRADED (an unproven hard dependency is a caution signal,
   not something to silently report as fully healthy)
6. intrinsic HEALTHY/DEGRADED, all HARD deps HEALTHY/DEGRADED (or no HARD
   deps at all) -> effective = intrinsic
7. SOFT dependency failures are recorded as informational evidence only
   and never change effective health.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from control_center.deployment_health import (
    DependencyRelationship,
    DeploymentEvidence,
    DeploymentInventory,
    DeploymentService,
    EvidenceSource,
    parse_image_reference,
)


class RuntimeHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ImageComparisonStatus(str, Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


class SourceAvailability(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    NOT_CONFIGURED = "not_configured"


@dataclass(frozen=True)
class RuntimeState:
    present: bool
    running: bool | None
    docker_health: str | None  # "healthy" | "unhealthy" | "starting" | None
    image_raw: str | None
    match_evidence: DeploymentEvidence | None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "present": self.present,
            "running": self.running,
            "docker_health": self.docker_health,
            "image": self.image_raw,
            "match_evidence": self.match_evidence.to_public_dict() if self.match_evidence else None,
        }


_NO_RUNTIME_STATE = RuntimeState(present=False, running=None, docker_health=None, image_raw=None, match_evidence=None)


# ---------------------------------------------------------------------------
# Container <-> service matching (section 9)
# ---------------------------------------------------------------------------


def _parse_compose_label(labels: str | None) -> str | None:
    if not labels:
        return None
    for pair in labels.split(","):
        key, _, value = pair.partition("=")
        if key.strip() == "com.docker.compose.service":
            return value.strip() or None
    return None


def match_containers_to_services(
    known_ids: set[str], containers: list[dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Deterministic service_id -> container matching. The Compose label
    `com.docker.compose.service` (set by Compose on every container it
    creates) is the strong evidence tier; an exact container-name match is
    the only fallback -- never a fuzzy/prefix-stripped guess. A duplicate
    match on either tier makes that service_id's runtime state UNKNOWN
    rather than silently picking one candidate (section 9: "never guess").
    """
    warnings: list[str] = []

    by_label: dict[str, dict[str, Any] | None] = {}
    for container in containers:
        service_id = _parse_compose_label(container.get("Labels"))
        if service_id and service_id in known_ids:
            if service_id in by_label:
                by_label[service_id] = None
                warnings.append(f"ambiguous_runtime_match:{service_id}")
            else:
                by_label[service_id] = container

    by_name: dict[str, dict[str, Any] | None] = {}
    for container in containers:
        name = (container.get("Names") or "").strip()
        if name in known_ids:
            if name in by_name:
                by_name[name] = None
                warnings.append(f"ambiguous_runtime_match:{name}")
            else:
                by_name[name] = container

    matched: dict[str, dict[str, Any]] = {}
    for service_id in known_ids:
        label_hit = by_label.get(service_id)
        if label_hit is not None:
            matched[service_id] = {"container": label_hit, "source": "label"}
            continue
        if service_id in by_label:
            # explicitly ambiguous on the strong-evidence tier -- do not
            # fall back to a weaker match for the same service_id.
            continue
        name_hit = by_name.get(service_id)
        if name_hit is not None:
            matched[service_id] = {"container": name_hit, "source": "name"}

    return matched, warnings


_STATUS_UNHEALTHY_RE = re.compile(r"\(unhealthy\)", re.IGNORECASE)
_STATUS_HEALTHY_RE = re.compile(r"\(healthy\)", re.IGNORECASE)
_STATUS_STARTING_RE = re.compile(r"\(health:\s*starting\)", re.IGNORECASE)


def _parse_docker_status(status: str) -> tuple[bool | None, str | None]:
    """From `docker ps`'s `Status` string (e.g. "Up 3 hours (healthy)",
    "Exited (0) 2 hours ago"). Never returns a made-up health value for a
    container with no healthcheck configured -- that stays None, distinct
    from an actual "unhealthy" reading."""
    if not status:
        return None, None
    running = status.startswith("Up")
    if not running:
        return running, None
    if _STATUS_UNHEALTHY_RE.search(status):
        return running, "unhealthy"
    if _STATUS_HEALTHY_RE.search(status):
        return running, "healthy"
    if _STATUS_STARTING_RE.search(status):
        return running, "starting"
    return running, None


def build_runtime_states(
    known_ids: set[str], containers: list[dict[str, Any]] | None
) -> tuple[dict[str, RuntimeState], list[str]]:
    """`containers=None` means Docker itself is unavailable -- every
    service gets `_NO_RUNTIME_STATE` (present=False), never a fabricated
    HEALTHY. This is the only path that distinguishes "Docker down" from
    "container not found"; both end up UNKNOWN downstream, which is the
    correct, conservative outcome for both."""
    if containers is None:
        return {service_id: _NO_RUNTIME_STATE for service_id in known_ids}, []

    matches, warnings = match_containers_to_services(known_ids, containers)
    states: dict[str, RuntimeState] = {}
    for service_id in known_ids:
        match = matches.get(service_id)
        if match is None:
            states[service_id] = _NO_RUNTIME_STATE
            continue
        container = match["container"]
        status = container.get("Status") or ""
        running, docker_health = _parse_docker_status(status)
        states[service_id] = RuntimeState(
            present=True,
            running=running,
            docker_health=docker_health,
            image_raw=container.get("Image") or None,
            match_evidence=DeploymentEvidence(
                EvidenceSource.DOCKER_INSPECT,
                f"matched a container via compose {match['source']} for '{service_id}'",
            ),
        )
    return states, warnings


# ---------------------------------------------------------------------------
# Intrinsic health (sections 7, 10)
# ---------------------------------------------------------------------------


def intrinsic_health(
    service_id: str, probe_result: dict[str, Any] | None, runtime: RuntimeState
) -> tuple[RuntimeHealth, DeploymentEvidence]:
    """application probe > Docker healthcheck > container running state >
    UNKNOWN. A recognized probe status is authoritative and short-circuits
    the rest; an unrecognized probe status is not trusted and falls
    through to the weaker evidence tiers rather than being guessed at."""
    if probe_result is not None:
        status = probe_result.get("status")
        if status == "UP":
            return RuntimeHealth.HEALTHY, DeploymentEvidence(
                EvidenceSource.HTTP_PROBE, f"application probe UP for '{service_id}'"
            )
        if status == "WARN":
            return RuntimeHealth.DEGRADED, DeploymentEvidence(
                EvidenceSource.HTTP_PROBE, f"application probe WARN for '{service_id}'"
            )
        if status == "DOWN":
            return RuntimeHealth.UNHEALTHY, DeploymentEvidence(
                EvidenceSource.HTTP_PROBE, f"application probe DOWN for '{service_id}'"
            )

    if runtime.docker_health == "healthy":
        return RuntimeHealth.HEALTHY, DeploymentEvidence(EvidenceSource.DOCKER_INSPECT, "docker healthcheck healthy")
    if runtime.docker_health == "unhealthy":
        return RuntimeHealth.UNHEALTHY, DeploymentEvidence(EvidenceSource.DOCKER_INSPECT, "docker healthcheck unhealthy")
    if runtime.docker_health == "starting":
        return RuntimeHealth.UNKNOWN, DeploymentEvidence(EvidenceSource.DOCKER_INSPECT, "docker healthcheck starting")

    if runtime.present and runtime.running:
        # CONTAINER RUNNING != SERVICE HEALTHY: no healthcheck/probe
        # evidence exists, so this stays UNKNOWN, never HEALTHY.
        return RuntimeHealth.UNKNOWN, DeploymentEvidence(
            EvidenceSource.DOCKER_INSPECT, "container running, no healthcheck or probe evidence"
        )
    if runtime.present and runtime.running is False:
        return RuntimeHealth.UNHEALTHY, DeploymentEvidence(EvidenceSource.DOCKER_INSPECT, "container present but not running")

    return RuntimeHealth.UNKNOWN, DeploymentEvidence(EvidenceSource.DOCKER_INSPECT, "no runtime evidence available")


# ---------------------------------------------------------------------------
# Dependency-aware effective health (sections 11, 12)
# ---------------------------------------------------------------------------


def effective_health(
    service_id: str,
    intrinsic: RuntimeHealth,
    dependency_edges: list[tuple[str, DependencyRelationship]],
    intrinsic_by_service: dict[str, RuntimeHealth],
) -> tuple[RuntimeHealth, tuple[DeploymentEvidence, ...]]:
    """See the module docstring's propagation table. `intrinsic_by_service`
    supplies only *intrinsic* values for dependency targets -- never
    effective -- which is what keeps this one-hop and cycle-safe."""
    evidence: list[DeploymentEvidence] = []

    if intrinsic is RuntimeHealth.UNHEALTHY:
        return RuntimeHealth.UNHEALTHY, tuple(evidence)

    hard_unhealthy: list[str] = []
    hard_unknown: list[str] = []
    for target, relationship in dependency_edges:
        target_health = intrinsic_by_service.get(target, RuntimeHealth.UNKNOWN)
        if relationship is DependencyRelationship.HARD:
            if target_health is RuntimeHealth.UNHEALTHY:
                hard_unhealthy.append(target)
            elif target_health is RuntimeHealth.UNKNOWN:
                hard_unknown.append(target)
        elif relationship is DependencyRelationship.SOFT and target_health in (
            RuntimeHealth.UNHEALTHY, RuntimeHealth.UNKNOWN,
        ):
            evidence.append(DeploymentEvidence(
                EvidenceSource.COMPOSE_DEPENDS_ON,
                f"soft dependency '{target}' is {target_health.value} (not applied to effective health)",
            ))

    if intrinsic is RuntimeHealth.UNKNOWN:
        if hard_unhealthy:
            evidence.append(DeploymentEvidence(
                EvidenceSource.COMPOSE_DEPENDS_ON,
                f"hard dependency unhealthy: {', '.join(sorted(hard_unhealthy))}",
            ))
            return RuntimeHealth.DEGRADED, tuple(evidence)
        return RuntimeHealth.UNKNOWN, tuple(evidence)

    # intrinsic is HEALTHY or DEGRADED here.
    if hard_unhealthy:
        evidence.append(DeploymentEvidence(
            EvidenceSource.COMPOSE_DEPENDS_ON,
            f"hard dependency unhealthy: {', '.join(sorted(hard_unhealthy))}",
        ))
        return RuntimeHealth.DEGRADED, tuple(evidence)
    if hard_unknown:
        evidence.append(DeploymentEvidence(
            EvidenceSource.COMPOSE_DEPENDS_ON,
            f"hard dependency unknown: {', '.join(sorted(hard_unknown))}",
        ))
        return RuntimeHealth.DEGRADED, tuple(evidence)

    return intrinsic, tuple(evidence)


# ---------------------------------------------------------------------------
# Image comparison (sections 20, 21)
# ---------------------------------------------------------------------------


def _normalize_repo(repository: str) -> str:
    """Strips Docker Hub's implicit namespacing so "mysql:8.0" (as
    written in Compose) and "docker.io/library/mysql:8.0" (as a running
    container often reports it) compare equal. `parse_image_reference`
    always splits a leading "docker.io" off into `registry` before this
    runs (it contains a "."), so only the remaining "library/" segment
    (Docker Hub's implicit namespace for official images) is ever seen
    here."""
    return repository.lower().removeprefix("library/")


def compare_image(configured, running_raw: str | None) -> tuple[ImageComparisonStatus, str | None, str | None]:
    """Conservative by design: any ambiguity (missing data, an
    unresolved `${VAR}`, either side untagged, either side `latest`)
    resolves to UNKNOWN rather than a guessed MATCH/MISMATCH -- `latest`
    is never treated as a verified version (section 21)."""
    if configured is None or running_raw is None:
        return ImageComparisonStatus.UNKNOWN, None, None
    if configured.has_variable or configured.repository is None:
        return ImageComparisonStatus.UNKNOWN, configured.raw, running_raw

    running_ref = parse_image_reference(running_raw)
    if running_ref.repository is None or running_ref.has_variable:
        return ImageComparisonStatus.UNKNOWN, configured.raw, running_raw

    configured_str = f"{configured.repository}:{configured.tag or '-'}"
    running_str = f"{running_ref.repository}:{running_ref.tag or '-'}"

    if _normalize_repo(configured.repository) != _normalize_repo(running_ref.repository):
        return ImageComparisonStatus.MISMATCH, configured_str, running_str

    if (configured.is_untagged or running_ref.is_untagged
            or configured.is_latest_tag or running_ref.is_latest_tag):
        return ImageComparisonStatus.UNKNOWN, configured_str, running_str

    if configured.tag == running_ref.tag:
        return ImageComparisonStatus.MATCH, configured_str, running_str
    return ImageComparisonStatus.MISMATCH, configured_str, running_str


# ---------------------------------------------------------------------------
# Response assembly (sections 6, 13, 14, 18, 19)
# ---------------------------------------------------------------------------


def _service_view(
    service: DeploymentService,
    runtime: RuntimeState,
    probe_result: dict[str, Any] | None,
    intrinsic: RuntimeHealth,
    intrinsic_evidence: DeploymentEvidence,
    effective: RuntimeHealth,
    effective_evidence: tuple[DeploymentEvidence, ...],
    dependency_views: list[dict[str, Any]],
    image_comparison: tuple[ImageComparisonStatus, str | None, str | None],
) -> dict[str, Any]:
    comparison_status, configured_image, running_image = image_comparison
    return {
        "service_id": service.service_id,
        "display_name": service.display_name,
        "category": service.category.value,
        "repository": service.repository,
        "deployment": {
            "image": service.image.to_public_dict() if service.image else None,
            "build_configured": service.build_configured,
            "healthcheck_configured": service.healthcheck_configured,
            "ports": list(service.ports),
        },
        "runtime": runtime.to_public_dict(),
        "health": {
            "intrinsic": intrinsic.value,
            "intrinsic_evidence": intrinsic_evidence.to_public_dict(),
            "effective": effective.value,
            "effective_evidence": [e.to_public_dict() for e in effective_evidence],
        },
        "image_comparison": {
            "status": comparison_status.value,
            "configured": configured_image,
            "running": running_image,
        },
        "dependencies": dependency_views,
        "evidence": [e.to_public_dict() for e in service.evidence],
        "completeness": service.completeness.to_public_dict(),
    }


def build_deployment_health_response(
    inventory: DeploymentInventory,
    *,
    generated_at: str,
    containers: list[dict[str, Any]] | None,
    probe_results: dict[str, dict[str, Any]] | None,
    prometheus_availability: SourceAvailability,
    regression_context: dict[str, Any],
) -> dict[str, Any]:
    """Pure assembly function -- see module docstring. `containers=None`
    means Docker is unavailable; `probe_results=None` means the
    application-probe config couldn't be loaded. Both degrade gracefully,
    never fail the response (only a Compose/DH-1 failure does that, and
    that's handled one layer up before this function is ever called)."""
    known_ids = {s.service_id for s in inventory.services}
    runtime_states, runtime_warnings = build_runtime_states(known_ids, containers)
    probe_source_available = probe_results is not None
    probe_results = probe_results or {}

    intrinsic_by_service: dict[str, RuntimeHealth] = {}
    intrinsic_evidence_by_service: dict[str, DeploymentEvidence] = {}
    for service in inventory.services:
        health, evidence = intrinsic_health(
            service.service_id, probe_results.get(service.service_id), runtime_states[service.service_id]
        )
        intrinsic_by_service[service.service_id] = health
        intrinsic_evidence_by_service[service.service_id] = evidence

    edges_by_service: dict[str, list[tuple[str, DependencyRelationship]]] = {sid: [] for sid in known_ids}
    dependents_view_by_service: dict[str, list[dict[str, Any]]] = {sid: [] for sid in known_ids}
    for dep in inventory.dependencies:
        edges_by_service.setdefault(dep.from_service, []).append((dep.to_service, dep.relationship))
        dependents_view_by_service.setdefault(dep.from_service, []).append({
            "to_service": dep.to_service,
            "relationship": dep.relationship.value,
            "target_intrinsic_health": intrinsic_by_service.get(dep.to_service, RuntimeHealth.UNKNOWN).value,
        })

    services_view: list[dict[str, Any]] = []
    counts = {"healthy": 0, "degraded": 0, "unhealthy": 0, "unknown": 0}

    for service in inventory.services:
        sid = service.service_id
        intrinsic = intrinsic_by_service[sid]
        effective, effective_evidence = effective_health(
            sid, intrinsic, edges_by_service.get(sid, []), intrinsic_by_service
        )
        counts[effective.value] += 1

        comparison = compare_image(service.image, runtime_states[sid].image_raw)

        services_view.append(_service_view(
            service, runtime_states[sid], probe_results.get(sid),
            intrinsic, intrinsic_evidence_by_service[sid],
            effective, effective_evidence,
            dependents_view_by_service.get(sid, []),
            comparison,
        ))

    total = len(inventory.services)
    summary = {"total": total, **counts}

    data_sources = {
        "compose": SourceAvailability.AVAILABLE.value,
        "docker": (SourceAvailability.AVAILABLE if containers is not None else SourceAvailability.UNAVAILABLE).value,
        "application_probe": (
            SourceAvailability.AVAILABLE if probe_source_available else SourceAvailability.UNAVAILABLE
        ).value,
        "prometheus": prometheus_availability.value,
        "regression_health": regression_context.get("availability", SourceAvailability.UNAVAILABLE.value),
    }

    return {
        "generated_at": generated_at,
        "baseline": inventory.baseline_source.value,
        "summary": summary,
        "services": services_view,
        "regression_health": {
            "availability": regression_context.get("availability"),
            "phases": regression_context.get("phases"),
            "freshness": regression_context.get("freshness"),
        },
        "data_sources": data_sources,
        "warnings": list(inventory.warnings) + runtime_warnings,
    }
