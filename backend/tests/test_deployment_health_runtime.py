"""
tests/test_deployment_health_runtime.py

Unit tests for control_center.deployment_health_runtime: matching Docker
containers to compose services (via compose label, exact-name fallback,
and ambiguity detection), parsing Docker status strings into RuntimeState,
intrinsic-health precedence (HTTP probe over Docker healthcheck over bare
running state), dependency-aware effective-health degradation, image
drift comparison (compare_image), and the full
build_deployment_health_response() assembly including its data-source
availability reporting, warning merging, drift/drift_summary wiring, and
its never-leaks-sensitive-data guarantee.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import json

from control_center.deployment_health import (
    BaselineSource,
    DependencyRelationship,
    EvidenceSource,
    parse_compose_text,
    parse_image_reference,
)
from control_center.deployment_health_runtime import (
    _NO_RUNTIME_STATE,
    RuntimeHealth,
    RuntimeState,
    SourceAvailability,
    build_deployment_health_response,
    build_runtime_states,
    compare_image,
    effective_health,
    intrinsic_health,
    match_containers_to_services,
)


def _running(healthy_suffix: str = "") -> str:
    """A "Up 3 hours" Docker status string with an optional healthcheck-state suffix appended."""
    return f"Up 3 hours{healthy_suffix}"


def _container(name: str, *, service_label: str | None = None, status: str = "Up 3 hours",
               image: str = "mysql:8.0", labels_extra: str = "") -> dict:
    """A `docker ps`-shaped container dict, with a compose service label injected into Labels when given."""
    labels = labels_extra
    if service_label:
        prefix = f"com.docker.compose.service={service_label}"
        labels = f"{prefix},{labels}" if labels else prefix
    return {"Names": name, "Status": status, "Image": image, "Labels": labels}


# ---------------------------------------------------------------------------
# Container <-> service matching
# ---------------------------------------------------------------------------


def test_match_via_compose_label():
    """A container carrying the compose service label is matched to that service_id via source="label"."""
    containers = [_container("proj-auth-1", service_label="auth-service")]
    matched, warnings = match_containers_to_services({"auth-service"}, containers)
    assert matched["auth-service"]["source"] == "label"
    assert warnings == []


def test_match_via_exact_name_fallback_when_no_label():
    """A container with no compose label but a name matching the service_id exactly is matched via source="name"."""
    containers = [_container("jupyter", service_label=None)]
    matched, warnings = match_containers_to_services({"jupyter"}, containers)
    assert matched["jupyter"]["source"] == "name"
    assert warnings == []


def test_label_takes_priority_over_name():
    """A container's compose label wins the match even when its container name doesn't match the service_id at all."""
    containers = [_container("weird-name", service_label="auth-service")]
    matched, _ = match_containers_to_services({"auth-service"}, containers)
    assert matched["auth-service"]["container"]["Names"] == "weird-name"


def test_ambiguous_label_match_yields_no_match_and_warning():
    """Two containers carrying the same compose service label produce no match for that service_id, flagged with an ambiguous_runtime_match warning."""
    containers = [
        _container("auth-1", service_label="auth-service"),
        _container("auth-2", service_label="auth-service"),
    ]
    matched, warnings = match_containers_to_services({"auth-service"}, containers)
    assert "auth-service" not in matched
    assert any("ambiguous_runtime_match:auth-service" in w for w in warnings)


def test_ambiguous_label_does_not_fall_back_to_name_match():
    """Label-tier ambiguity blocks the whole service_id even when one ambiguous container's name would otherwise match exactly."""
    # Even if one of the ambiguous containers happens to be named
    # exactly like the service, ambiguity on the strong-evidence tier
    # blocks the whole service_id, not just that tier.
    containers = [
        _container("auth-service", service_label="auth-service"),
        _container("auth-2", service_label="auth-service"),
    ]
    matched, _ = match_containers_to_services({"auth-service"}, containers)
    assert "auth-service" not in matched


def test_no_match_for_unrelated_containers():
    """A container matching neither the compose service label nor the exact name of the target service_id produces no match."""
    containers = [_container("something-else", service_label="something-else")]
    matched, _ = match_containers_to_services({"auth-service"}, containers)
    assert "auth-service" not in matched


def test_labels_present_but_no_compose_service_key_falls_back_to_name():
    """A container with labels but no com.docker.compose.service key still falls back to exact-name matching."""
    containers = [_container("auth-service", service_label=None, labels_extra="some.other.label=x")]
    matched, warnings = match_containers_to_services({"auth-service"}, containers)
    assert matched["auth-service"]["source"] == "name"
    assert warnings == []


def test_ambiguous_name_match_yields_no_match_and_warning():
    """Two containers both named exactly like the service_id (no distinguishing label) produce no match, flagged with an ambiguous_runtime_match warning."""
    containers = [
        {"Names": "jupyter", "Status": "Up", "Image": "a", "Labels": ""},
        {"Names": "jupyter", "Status": "Up", "Image": "b", "Labels": ""},
    ]
    matched, warnings = match_containers_to_services({"jupyter"}, containers)
    assert "jupyter" not in matched
    assert any("ambiguous_runtime_match:jupyter" in w for w in warnings)


# ---------------------------------------------------------------------------
# Docker status parsing / runtime state building
# ---------------------------------------------------------------------------


def test_build_runtime_states_healthy():
    """A container with status "Up ... (healthy)" is parsed as present, running, with docker_health="healthy"."""
    containers = [_container("mysql", service_label="mysql", status="Up 3 hours (healthy)")]
    states, warnings = build_runtime_states({"mysql"}, containers)
    assert states["mysql"].present is True
    assert states["mysql"].running is True
    assert states["mysql"].docker_health == "healthy"
    assert warnings == []


def test_build_runtime_states_unhealthy():
    """A container with status "Up ... (unhealthy)" is parsed with docker_health="unhealthy"."""
    containers = [_container("mysql", service_label="mysql", status="Up 1 hour (unhealthy)")]
    states, _ = build_runtime_states({"mysql"}, containers)
    assert states["mysql"].docker_health == "unhealthy"


def test_build_runtime_states_starting():
    """A container with status "Up ... (health: starting)" is parsed with docker_health="starting"."""
    containers = [_container("mysql", service_label="mysql", status="Up 10 seconds (health: starting)")]
    states, _ = build_runtime_states({"mysql"}, containers)
    assert states["mysql"].docker_health == "starting"


def test_build_runtime_states_running_no_healthcheck():
    """A plain "Up 3 hours" status (no healthcheck suffix) is parsed as running with docker_health=None."""
    containers = [_container("mysql", service_label="mysql", status="Up 3 hours")]
    states, _ = build_runtime_states({"mysql"}, containers)
    assert states["mysql"].running is True
    assert states["mysql"].docker_health is None


def test_build_runtime_states_stopped():
    """An "Exited (0) ..." status is parsed as present but not running."""
    containers = [_container("mysql", service_label="mysql", status="Exited (0) 2 hours ago")]
    states, _ = build_runtime_states({"mysql"}, containers)
    assert states["mysql"].present is True
    assert states["mysql"].running is False


def test_build_runtime_states_missing_service_stays_unknown():
    """A service_id with no matching container gets the shared _NO_RUNTIME_STATE sentinel."""
    states, _ = build_runtime_states({"mysql"}, [])
    assert states["mysql"] is _NO_RUNTIME_STATE


def test_build_runtime_states_empty_status_string():
    """An empty status string parses to running=None and docker_health=None, rather than raising or guessing."""
    containers = [_container("mysql", service_label="mysql", status="")]
    states, _ = build_runtime_states({"mysql"}, containers)
    assert states["mysql"].running is None
    assert states["mysql"].docker_health is None


def test_build_runtime_states_docker_unavailable_is_none_containers():
    """With containers=None (Docker itself unreachable), every service gets the shared _NO_RUNTIME_STATE sentinel and no warnings."""
    states, warnings = build_runtime_states({"mysql", "redis"}, None)
    assert all(s is _NO_RUNTIME_STATE for s in states.values())
    assert warnings == []


def test_runtime_state_never_includes_container_id():
    """A RuntimeState's to_public_dict() never includes the raw Docker container ID, even when the source container carried one."""
    containers = [_container("mysql", service_label="mysql")]
    containers[0]["ID"] = "abc123deadbeef"
    states, _ = build_runtime_states({"mysql"}, containers)
    payload = json.dumps(states["mysql"].to_public_dict())
    assert "abc123deadbeef" not in payload


# ---------------------------------------------------------------------------
# Intrinsic health precedence
# ---------------------------------------------------------------------------


def test_intrinsic_health_application_probe_up():
    """An HTTP probe with status "UP" gives HEALTHY, evidenced by HTTP_PROBE."""
    health, evidence = intrinsic_health("x", {"status": "UP"}, _NO_RUNTIME_STATE)
    assert health is RuntimeHealth.HEALTHY
    assert evidence.source is EvidenceSource.HTTP_PROBE


def test_intrinsic_health_application_probe_warn():
    """An HTTP probe with status "WARN" gives DEGRADED."""
    health, _ = intrinsic_health("x", {"status": "WARN"}, _NO_RUNTIME_STATE)
    assert health is RuntimeHealth.DEGRADED


def test_intrinsic_health_application_probe_down():
    """An HTTP probe with status "DOWN" gives UNHEALTHY."""
    health, _ = intrinsic_health("x", {"status": "DOWN"}, _NO_RUNTIME_STATE)
    assert health is RuntimeHealth.UNHEALTHY


def test_intrinsic_health_probe_wins_over_docker_healthcheck():
    """A passing HTTP probe overrides a failing Docker healthcheck: intrinsic health is HEALTHY, evidenced by HTTP_PROBE."""
    runtime = RuntimeState(present=True, running=True, docker_health="unhealthy", image_raw=None, match_evidence=None)
    health, evidence = intrinsic_health("x", {"status": "UP"}, runtime)
    assert health is RuntimeHealth.HEALTHY
    assert evidence.source is EvidenceSource.HTTP_PROBE


def test_intrinsic_health_docker_healthcheck_when_no_probe():
    """With no HTTP probe result, a healthy Docker healthcheck gives HEALTHY, evidenced by DOCKER_INSPECT."""
    runtime = RuntimeState(present=True, running=True, docker_health="healthy", image_raw=None, match_evidence=None)
    health, evidence = intrinsic_health("x", None, runtime)
    assert health is RuntimeHealth.HEALTHY
    assert evidence.source is EvidenceSource.DOCKER_INSPECT


def test_intrinsic_health_docker_healthcheck_unhealthy():
    """With no HTTP probe result, an unhealthy Docker healthcheck gives UNHEALTHY."""
    runtime = RuntimeState(present=True, running=True, docker_health="unhealthy", image_raw=None, match_evidence=None)
    health, _ = intrinsic_health("x", None, runtime)
    assert health is RuntimeHealth.UNHEALTHY


def test_intrinsic_health_docker_healthcheck_starting_is_unknown():
    """A Docker healthcheck still in the "starting" grace period gives UNKNOWN, not a false positive/negative."""
    runtime = RuntimeState(present=True, running=True, docker_health="starting", image_raw=None, match_evidence=None)
    health, evidence = intrinsic_health("x", None, runtime)
    assert health is RuntimeHealth.UNKNOWN
    assert evidence.source is EvidenceSource.DOCKER_INSPECT


def test_intrinsic_health_running_without_healthcheck_is_unknown_not_healthy():
    """A running container with no configured healthcheck gives UNKNOWN -- container running is not evidence of service health."""
    # CONTAINER RUNNING != SERVICE HEALTHY
    runtime = RuntimeState(present=True, running=True, docker_health=None, image_raw=None, match_evidence=None)
    health, _ = intrinsic_health("x", None, runtime)
    assert health is RuntimeHealth.UNKNOWN


def test_intrinsic_health_stopped_container_is_unhealthy():
    """A present but non-running container gives UNHEALTHY."""
    runtime = RuntimeState(present=True, running=False, docker_health=None, image_raw=None, match_evidence=None)
    health, _ = intrinsic_health("x", None, runtime)
    assert health is RuntimeHealth.UNHEALTHY


def test_intrinsic_health_no_evidence_is_unknown():
    """With no probe result and the shared _NO_RUNTIME_STATE sentinel, intrinsic health is UNKNOWN."""
    health, _ = intrinsic_health("x", None, _NO_RUNTIME_STATE)
    assert health is RuntimeHealth.UNKNOWN


def test_intrinsic_health_unrecognized_probe_status_falls_through():
    """An HTTP probe with an unrecognized status string ("WEIRD") is ignored, falling through to the Docker healthcheck evidence."""
    runtime = RuntimeState(present=True, running=True, docker_health="healthy", image_raw=None, match_evidence=None)
    health, evidence = intrinsic_health("x", {"status": "WEIRD"}, runtime)
    assert health is RuntimeHealth.HEALTHY
    assert evidence.source is EvidenceSource.DOCKER_INSPECT


# ---------------------------------------------------------------------------
# Dependency-aware effective health
# ---------------------------------------------------------------------------


def test_effective_health_intrinsic_unhealthy_ignores_dependencies():
    """A service whose own intrinsic health is UNHEALTHY stays UNHEALTHY regardless of its dependencies' health."""
    health, _ = effective_health(
        "a", RuntimeHealth.UNHEALTHY,
        [("b", DependencyRelationship.HARD)],
        {"b": RuntimeHealth.HEALTHY},
    )
    assert health is RuntimeHealth.UNHEALTHY


def test_effective_health_hard_dependency_unhealthy_degrades_healthy_intrinsic():
    """A HEALTHY service with an UNHEALTHY hard dependency is degraded to DEGRADED, with evidence naming the dependency."""
    # TES/ToolServer example from the brief.
    health, evidence = effective_health(
        "tes", RuntimeHealth.HEALTHY,
        [("toolserver", DependencyRelationship.HARD)],
        {"toolserver": RuntimeHealth.UNHEALTHY},
    )
    assert health is RuntimeHealth.DEGRADED
    assert any("toolserver" in e.detail for e in evidence)


def test_effective_health_soft_dependency_failure_does_not_degrade():
    """A HEALTHY service with an UNHEALTHY soft dependency stays HEALTHY, with evidence noting the soft dependency."""
    health, evidence = effective_health(
        "a", RuntimeHealth.HEALTHY,
        [("b", DependencyRelationship.SOFT)],
        {"b": RuntimeHealth.UNHEALTHY},
    )
    assert health is RuntimeHealth.HEALTHY
    assert any("soft dependency" in e.detail for e in evidence)


def test_effective_health_hard_dependency_unknown_degrades():
    """A HEALTHY service with a hard dependency whose health is UNKNOWN is degraded to DEGRADED."""
    health, _ = effective_health(
        "a", RuntimeHealth.HEALTHY,
        [("b", DependencyRelationship.HARD)],
        {"b": RuntimeHealth.UNKNOWN},
    )
    assert health is RuntimeHealth.DEGRADED


def test_effective_health_no_bad_dependencies_stays_intrinsic():
    """With every hard dependency HEALTHY, effective health equals the intrinsic health, with no evidence entries."""
    health, evidence = effective_health(
        "a", RuntimeHealth.HEALTHY,
        [("b", DependencyRelationship.HARD)],
        {"b": RuntimeHealth.HEALTHY},
    )
    assert health is RuntimeHealth.HEALTHY
    assert evidence == ()


def test_effective_health_intrinsic_unknown_no_bad_hard_deps_stays_unknown():
    """A service with UNKNOWN intrinsic health and no dependencies stays UNKNOWN."""
    health, _ = effective_health("a", RuntimeHealth.UNKNOWN, [], {})
    assert health is RuntimeHealth.UNKNOWN


def test_effective_health_intrinsic_unknown_with_hard_unhealthy_becomes_degraded():
    """A service with UNKNOWN intrinsic health and an UNHEALTHY hard dependency becomes DEGRADED."""
    health, _ = effective_health(
        "a", RuntimeHealth.UNKNOWN,
        [("b", DependencyRelationship.HARD)],
        {"b": RuntimeHealth.UNHEALTHY},
    )
    assert health is RuntimeHealth.DEGRADED


def test_effective_health_never_escalates_degraded_to_unhealthy_from_dependency():
    """A DEGRADED intrinsic health is never escalated to UNHEALTHY purely because of a dependency's failure."""
    health, _ = effective_health(
        "a", RuntimeHealth.DEGRADED,
        [("b", DependencyRelationship.HARD)],
        {"b": RuntimeHealth.UNHEALTHY},
    )
    assert health is RuntimeHealth.DEGRADED


def test_effective_health_dependency_cycle_does_not_hang_or_recurse():
    """A mutual HARD dependency cycle (A<->B) terminates without hanging, since only pre-computed one-hop intrinsic values are consulted."""
    # A <-> B, both HARD. Only intrinsic values are consulted (one-hop),
    # so a cycle is not a special case at all -- this simply terminates.
    intrinsic_by_service = {"a": RuntimeHealth.HEALTHY, "b": RuntimeHealth.UNHEALTHY}
    health_a, _ = effective_health("a", RuntimeHealth.HEALTHY, [("b", DependencyRelationship.HARD)], intrinsic_by_service)
    health_b, _ = effective_health("b", RuntimeHealth.UNHEALTHY, [("a", DependencyRelationship.HARD)], intrinsic_by_service)
    assert health_a is RuntimeHealth.DEGRADED  # a's own intrinsic is fine, b is down
    assert health_b is RuntimeHealth.UNHEALTHY  # b's own intrinsic already failed


def test_effective_health_missing_dependency_target_is_treated_as_unknown():
    """A hard dependency on a service_id with no intrinsic-health entry at all is treated as UNKNOWN, degrading the caller."""
    health, _ = effective_health(
        "a", RuntimeHealth.HEALTHY,
        [("ghost", DependencyRelationship.HARD)],
        {},  # "ghost" has no intrinsic entry at all
    )
    assert health is RuntimeHealth.DEGRADED  # HARD dep unknown -> degraded per the table


# ---------------------------------------------------------------------------
# Image comparison
# ---------------------------------------------------------------------------


def test_compare_image_match():
    """The same repository:tag on both sides gives status "match", with both normalized strings echoed back."""
    configured = parse_image_reference("mysql:8.0")
    status, c, r = compare_image(configured, "mysql:8.0")
    assert status.value == "match"
    assert c == "mysql:8.0" and r == "mysql:8.0"


def test_compare_image_match_with_registry_normalization():
    """"mysql:8.0" matches "docker.io/library/mysql:8.0" -- Docker's implicit default registry/namespace is normalized away."""
    configured = parse_image_reference("mysql:8.0")
    status, _, _ = compare_image(configured, "docker.io/library/mysql:8.0")
    assert status.value == "match"


def test_compare_image_mismatch_tag():
    """The same repository with a different tag gives status "mismatch"."""
    configured = parse_image_reference("mysql:8.0")
    status, _, _ = compare_image(configured, "mysql:5.7")
    assert status.value == "mismatch"


def test_compare_image_mismatch_repository():
    """A different repository entirely gives status "mismatch"."""
    configured = parse_image_reference("mysql:8.0")
    status, _, _ = compare_image(configured, "postgres:8.0")
    assert status.value == "mismatch"


def test_compare_image_unknown_when_missing():
    """With no configured image reference at all, comparison gives status "unknown" with both sides None."""
    status, c, r = compare_image(None, "mysql:8.0")
    assert status.value == "unknown"
    assert c is None and r is None


def test_compare_image_unknown_when_configured_has_variable():
    """A configured image containing an unresolved ${TAG} variable can't be meaningfully compared, giving status "unknown"."""
    configured = parse_image_reference("mysql:${TAG}")
    status, _, _ = compare_image(configured, "mysql:8.0")
    assert status.value == "unknown"


def test_compare_image_unknown_when_either_side_untagged():
    """An untagged configured image (no tag, no digest) can't be meaningfully compared, giving status "unknown"."""
    configured = parse_image_reference("mysql")
    status, _, _ = compare_image(configured, "mysql:8.0")
    assert status.value == "unknown"


def test_compare_image_unknown_when_either_side_latest():
    """Even an exact ":latest" match on both sides gives status "unknown" -- "latest" is never a verified match."""
    configured = parse_image_reference("mysql:latest")
    status, _, _ = compare_image(configured, "mysql:latest")
    assert status.value == "unknown"  # "latest" is never a verified match


def test_compare_image_unknown_when_running_has_variable():
    """A running image string containing an unresolved ${TAG} variable can't be meaningfully compared, giving status "unknown"."""
    configured = parse_image_reference("mysql:8.0")
    status, _, _ = compare_image(configured, "mysql:${TAG}")
    assert status.value == "unknown"


# ---------------------------------------------------------------------------
# Full response assembly
# ---------------------------------------------------------------------------

_COMPOSE = """
services:
  mysql:
    image: mysql:8.0
    healthcheck:
      test: ["CMD", "true"]
  auth-service:
    image: ghcr.io/omnibioai/omnibioai-auth:latest
    depends_on:
      mysql:
        condition: service_healthy
  api-gateway:
    image: ghcr.io/omnibioai/omnibioai-api-gateway:latest
    depends_on:
      auth-service:
        condition: service_started
"""


def _inventory():
    """A parsed inventory from the module's fixed 3-service _COMPOSE fixture, with baseline_source=DEVELOPMENT."""
    return parse_compose_text(_COMPOSE, baseline_source=BaselineSource.DEVELOPMENT)


def test_summary_counts_are_dynamic_not_hardcoded():
    """The response's summary.total equals the inventory's actual service count, and its health-bucket counts sum to that total."""
    inventory = _inventory()
    response = build_deployment_health_response(
        inventory, generated_at="2026-08-30T00:00:00Z",
        containers=[], probe_results={},
        prometheus_availability=SourceAvailability.NOT_CONFIGURED,
        regression_context={"availability": "unavailable", "phases": None, "freshness": None},
    )
    assert response["summary"]["total"] == len(inventory.services) == 3
    assert sum(response["summary"][k] for k in ("healthy", "degraded", "unhealthy", "unknown")) == 3


def test_docker_unavailable_never_becomes_healthy():
    """With containers=None and probe_results=None (both sources unreachable), every service's intrinsic health is "unknown" and runtime.present is False, never a fabricated "healthy"."""
    inventory = _inventory()
    response = build_deployment_health_response(
        inventory, generated_at="2026-08-30T00:00:00Z",
        containers=None, probe_results=None,
        prometheus_availability=SourceAvailability.NOT_CONFIGURED,
        regression_context={"availability": "unavailable", "phases": None, "freshness": None},
    )
    assert response["data_sources"]["docker"] == "unavailable"
    assert response["data_sources"]["application_probe"] == "unavailable"
    for service in response["services"]:
        assert service["health"]["intrinsic"] == "unknown"
        assert service["runtime"]["present"] is False


def test_dependency_degradation_reflected_in_response():
    """A soft dependency (api-gateway's own failing probe) makes it intrinsically unhealthy regardless of dependency chains, while auth-service's healthy hard dependency (mysql) leaves it fully healthy."""
    inventory = _inventory()
    containers = [
        _container("mysql", service_label="mysql", status="Up 1 hour (healthy)"),
    ]
    probe_results = {
        "auth-service": {"name": "auth-service", "status": "UP"},
        "api-gateway": {"name": "api-gateway", "status": "DOWN"},
    }
    response = build_deployment_health_response(
        inventory, generated_at="2026-08-30T00:00:00Z",
        containers=containers, probe_results=probe_results,
        prometheus_availability=SourceAvailability.NOT_CONFIGURED,
        regression_context={"availability": "unavailable", "phases": None, "freshness": None},
    )
    by_id = {s["service_id"]: s for s in response["services"]}
    assert by_id["mysql"]["health"]["effective"] == "healthy"
    assert by_id["auth-service"]["health"]["intrinsic"] == "healthy"
    assert by_id["auth-service"]["health"]["effective"] == "healthy"  # its hard dep (mysql) is healthy
    assert by_id["api-gateway"]["health"]["intrinsic"] == "unhealthy"
    assert by_id["api-gateway"]["health"]["effective"] == "unhealthy"  # intrinsic failure, deps irrelevant


def test_regression_health_context_is_compact_no_capabilities_or_findings():
    """The response's regression_health mirrors the caller-supplied regression_context verbatim, and the serialized response never mentions capabilities/findings/technical_debt."""
    inventory = _inventory()
    regression_context = {
        "availability": "available",
        "phases": {"p0": {"status": "complete", "certification_status": "certified"}},
        "freshness": {"status": "CURRENT"},
    }
    response = build_deployment_health_response(
        inventory, generated_at="2026-08-30T00:00:00Z",
        containers=[], probe_results={},
        prometheus_availability=SourceAvailability.NOT_CONFIGURED,
        regression_context=regression_context,
    )
    assert response["regression_health"] == {
        "availability": "available",
        "phases": {"p0": {"status": "complete", "certification_status": "certified"}},
        "freshness": {"status": "CURRENT"},
    }
    payload = json.dumps(response)
    assert "capabilities" not in payload
    assert "findings" not in payload
    assert "technical_debt" not in payload


def test_data_source_availability_shape():
    """The response's data_sources dict reports "available"/"not_configured" per source (compose/docker/application_probe/prometheus/regression_health), matching the caller-supplied inputs."""
    inventory = _inventory()
    response = build_deployment_health_response(
        inventory, generated_at="2026-08-30T00:00:00Z",
        containers=[], probe_results={"mysql": {"name": "mysql", "status": "UP"}},
        prometheus_availability=SourceAvailability.AVAILABLE,
        regression_context={"availability": "available", "phases": {}, "freshness": None},
    )
    assert response["data_sources"] == {
        "compose": "available",
        "docker": "available",
        "application_probe": "available",
        "prometheus": "available",
        "regression_health": "available",
    }


def test_generated_at_passthrough():
    """The response's generated_at field echoes the caller-supplied timestamp verbatim."""
    inventory = _inventory()
    response = build_deployment_health_response(
        inventory, generated_at="2026-08-30T12:34:56+00:00",
        containers=[], probe_results={},
        prometheus_availability=SourceAvailability.NOT_CONFIGURED,
        regression_context={"availability": "unavailable", "phases": None, "freshness": None},
    )
    assert response["generated_at"] == "2026-08-30T12:34:56+00:00"


def test_warnings_merge_compose_and_runtime_warnings():
    """The response's warnings list includes both a compose-parsing warning (unknown_dependency_target) and a runtime-matching warning (ambiguous_runtime_match)."""
    inventory = parse_compose_text("""
services:
  a:
    image: something
    depends_on:
      - ghost
""")
    containers = [
        _container("c1", service_label="a"),
        _container("c2", service_label="a"),
    ]
    response = build_deployment_health_response(
        inventory, generated_at="2026-08-30T00:00:00Z",
        containers=containers, probe_results={},
        prometheus_availability=SourceAvailability.NOT_CONFIGURED,
        regression_context={"availability": "unavailable", "phases": None, "freshness": None},
    )
    assert any("unknown_dependency_target" in w for w in response["warnings"])
    assert any("ambiguous_runtime_match" in w for w in response["warnings"])


def test_response_never_leaks_sensitive_data():
    """The full serialized response never contains a raw container ID, filesystem path, or any secret/password/token marker."""
    inventory = _inventory()
    containers = [_container("mysql", service_label="mysql")]
    containers[0]["ID"] = "deadbeef1234"
    response = build_deployment_health_response(
        inventory, generated_at="2026-08-30T00:00:00Z",
        containers=containers, probe_results={},
        prometheus_availability=SourceAvailability.NOT_CONFIGURED,
        regression_context={"availability": "unavailable", "phases": None, "freshness": None},
    )
    payload_lower = json.dumps(response).lower()
    for marker in ("deadbeef1234", "/home/", "password", "secret", "token", "container_id"):
        assert marker not in payload_lower


def test_no_crash_for_third_party_service_with_unknown_ownership_and_category():
    """A service with unresolvable ownership and category assembles cleanly into the response, with repository=None, category="unknown", and health "unknown" -- never a crash or a guessed value."""
    inventory = parse_compose_text("""
services:
  mystery:
    image: some-third-party/thing:1.0
""")
    response = build_deployment_health_response(
        inventory, generated_at="2026-08-30T00:00:00Z",
        containers=[], probe_results={},
        prometheus_availability=SourceAvailability.NOT_CONFIGURED,
        regression_context={"availability": "unavailable", "phases": None, "freshness": None},
    )
    service = response["services"][0]
    assert service["repository"] is None
    assert service["category"] == "unknown"
    assert service["health"]["intrinsic"] == "unknown"


# ---------------------------------------------------------------------------
# DH-5: drift integration -- `local_image_ids` is an optional, keyword-only,
# defaulted parameter; every test above this section omits it entirely and
# already proves backward compatibility (existing callers/tests untouched,
# no signature break). These tests cover the new `drift` / `drift_summary`
# wiring itself, end to end through `build_deployment_health_response`.
# ---------------------------------------------------------------------------


def test_drift_key_present_for_every_service_and_defaults_safely():
    """No containers, no local_image_ids: mysql (no repository ownership
    evidence) is NOT_APPLICABLE; the two OmniBioAI-owned services are
    UNKNOWN (no running container to compare against) -- never a
    fabricated MATCH."""
    inventory = _inventory()
    response = build_deployment_health_response(
        inventory, generated_at="2026-08-30T00:00:00Z",
        containers=[], probe_results={},
        prometheus_availability=SourceAvailability.NOT_CONFIGURED,
        regression_context={"availability": "unavailable", "phases": None, "freshness": None},
    )
    by_id = {s["service_id"]: s for s in response["services"]}
    for service_id in ("mysql", "auth-service", "api-gateway"):
        assert "drift" in by_id[service_id]
        for key in ("source", "configured", "running", "drift"):
            assert key in by_id[service_id]["drift"]
    assert by_id["mysql"]["drift"]["drift"]["status"] == "not_applicable"
    assert by_id["auth-service"]["drift"]["drift"]["status"] == "unknown"
    assert by_id["api-gateway"]["drift"]["drift"]["status"] == "unknown"


def test_drift_summary_present_and_matches_per_service_counts():
    """The response's drift_summary counts sum to the total service count, and remains a distinct dimension from the health summary."""
    inventory = _inventory()
    response = build_deployment_health_response(
        inventory, generated_at="2026-08-30T00:00:00Z",
        containers=[], probe_results={},
        prometheus_availability=SourceAvailability.NOT_CONFIGURED,
        regression_context={"availability": "unavailable", "phases": None, "freshness": None},
    )
    assert response["drift_summary"] == {"match": 0, "drifted": 0, "unknown": 2, "not_applicable": 1}
    assert sum(response["drift_summary"].values()) == response["summary"]["total"]
    # drift_summary is a distinct dimension from the health summary --
    # never replacing or merging into it.
    assert set(response["summary"]) == {"total", "healthy", "degraded", "unhealthy", "unknown"}


def test_drift_match_end_to_end_via_local_image_ids():
    """When a running container's image id matches the locally-built id for the configured image, drift status is "match" end to end through the full response."""
    inventory = _inventory()
    containers = [
        _container(
            "auth-1", service_label="auth-service",
            labels_extra="com.docker.compose.image=sha256:abc123",
        ),
    ]
    local_image_ids = {"ghcr.io/omnibioai/omnibioai-auth:latest": "sha256:abc123"}
    response = build_deployment_health_response(
        inventory, generated_at="2026-08-30T00:00:00Z",
        containers=containers, probe_results={},
        prometheus_availability=SourceAvailability.NOT_CONFIGURED,
        regression_context={"availability": "unavailable", "phases": None, "freshness": None},
        local_image_ids=local_image_ids,
    )
    by_id = {s["service_id"]: s for s in response["services"]}
    drift = by_id["auth-service"]["drift"]
    assert drift["drift"]["status"] == "match"
    assert drift["running"]["image_id"] == "sha256:abc123"
    assert len(drift["drift"]["evidence"]) == 1
    assert response["drift_summary"]["match"] == 1


def test_drift_drifted_end_to_end_when_local_image_id_differs():
    """When a running container's image id differs from the locally-built id for the configured image, drift status is "drifted" end to end through the full response."""
    inventory = _inventory()
    containers = [
        _container(
            "auth-1", service_label="auth-service",
            labels_extra="com.docker.compose.image=sha256:running-old",
        ),
    ]
    local_image_ids = {"ghcr.io/omnibioai/omnibioai-auth:latest": "sha256:rebuilt-new"}
    response = build_deployment_health_response(
        inventory, generated_at="2026-08-30T00:00:00Z",
        containers=containers, probe_results={},
        prometheus_availability=SourceAvailability.NOT_CONFIGURED,
        regression_context={"availability": "unavailable", "phases": None, "freshness": None},
        local_image_ids=local_image_ids,
    )
    by_id = {s["service_id"]: s for s in response["services"]}
    assert by_id["auth-service"]["drift"]["drift"]["status"] == "drifted"
    assert response["drift_summary"]["drifted"] == 1


def test_drift_third_party_service_stays_not_applicable_regardless_of_docker_state():
    """A service with no repository ownership evidence (mysql) stays drift status "not_applicable" regardless of whether Docker/containers are unavailable, empty, or present."""
    inventory = _inventory()
    for containers in (None, [], [_container("mysql-1", service_label="mysql")]):
        response = build_deployment_health_response(
            inventory, generated_at="2026-08-30T00:00:00Z",
            containers=containers, probe_results={},
            prometheus_availability=SourceAvailability.NOT_CONFIGURED,
            regression_context={"availability": "unavailable", "phases": None, "freshness": None},
        )
        by_id = {s["service_id"]: s for s in response["services"]}
        assert by_id["mysql"]["drift"]["drift"]["status"] == "not_applicable"


def test_docker_unavailable_drift_degrades_to_unknown_not_fabricated_match():
    """With Docker entirely unavailable, every owned service's drift status is "unknown" and drift_summary's match/drifted counts are both zero -- never a fabricated match."""
    inventory = _inventory()
    response = build_deployment_health_response(
        inventory, generated_at="2026-08-30T00:00:00Z",
        containers=None, probe_results=None,
        prometheus_availability=SourceAvailability.NOT_CONFIGURED,
        regression_context={"availability": "unavailable", "phases": None, "freshness": None},
    )
    by_id = {s["service_id"]: s for s in response["services"]}
    assert by_id["auth-service"]["drift"]["drift"]["status"] == "unknown"
    assert by_id["api-gateway"]["drift"]["drift"]["status"] == "unknown"
    assert response["drift_summary"]["match"] == 0
    assert response["drift_summary"]["drifted"] == 0


def test_drift_never_leaks_sensitive_data_in_full_response():
    """The full response, including its drift data with local_image_ids supplied, never contains a filesystem path or any secret/password/token/container-id marker."""
    inventory = _inventory()
    containers = [
        _container(
            "auth-1", service_label="auth-service",
            labels_extra="com.docker.compose.image=sha256:abc123",
        ),
    ]
    response = build_deployment_health_response(
        inventory, generated_at="2026-08-30T00:00:00Z",
        containers=containers, probe_results={},
        prometheus_availability=SourceAvailability.NOT_CONFIGURED,
        regression_context={"availability": "unavailable", "phases": None, "freshness": None},
        local_image_ids={"ghcr.io/omnibioai/omnibioai-auth:latest": "sha256:abc123"},
    )
    payload_lower = json.dumps(response).lower()
    for marker in ("/home/", "password", "secret", "token", "container_id"):
        assert marker not in payload_lower
