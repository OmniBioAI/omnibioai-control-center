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
    return f"Up 3 hours{healthy_suffix}"


def _container(name: str, *, service_label: str | None = None, status: str = "Up 3 hours",
               image: str = "mysql:8.0", labels_extra: str = "") -> dict:
    labels = labels_extra
    if service_label:
        prefix = f"com.docker.compose.service={service_label}"
        labels = f"{prefix},{labels}" if labels else prefix
    return {"Names": name, "Status": status, "Image": image, "Labels": labels}


# ---------------------------------------------------------------------------
# Container <-> service matching
# ---------------------------------------------------------------------------


def test_match_via_compose_label():
    containers = [_container("proj-auth-1", service_label="auth-service")]
    matched, warnings = match_containers_to_services({"auth-service"}, containers)
    assert matched["auth-service"]["source"] == "label"
    assert warnings == []


def test_match_via_exact_name_fallback_when_no_label():
    containers = [_container("jupyter", service_label=None)]
    matched, warnings = match_containers_to_services({"jupyter"}, containers)
    assert matched["jupyter"]["source"] == "name"
    assert warnings == []


def test_label_takes_priority_over_name():
    containers = [_container("weird-name", service_label="auth-service")]
    matched, _ = match_containers_to_services({"auth-service"}, containers)
    assert matched["auth-service"]["container"]["Names"] == "weird-name"


def test_ambiguous_label_match_yields_no_match_and_warning():
    containers = [
        _container("auth-1", service_label="auth-service"),
        _container("auth-2", service_label="auth-service"),
    ]
    matched, warnings = match_containers_to_services({"auth-service"}, containers)
    assert "auth-service" not in matched
    assert any("ambiguous_runtime_match:auth-service" in w for w in warnings)


def test_ambiguous_label_does_not_fall_back_to_name_match():
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
    containers = [_container("something-else", service_label="something-else")]
    matched, _ = match_containers_to_services({"auth-service"}, containers)
    assert "auth-service" not in matched


def test_labels_present_but_no_compose_service_key_falls_back_to_name():
    containers = [_container("auth-service", service_label=None, labels_extra="some.other.label=x")]
    matched, warnings = match_containers_to_services({"auth-service"}, containers)
    assert matched["auth-service"]["source"] == "name"
    assert warnings == []


def test_ambiguous_name_match_yields_no_match_and_warning():
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
    containers = [_container("mysql", service_label="mysql", status="Up 3 hours (healthy)")]
    states, warnings = build_runtime_states({"mysql"}, containers)
    assert states["mysql"].present is True
    assert states["mysql"].running is True
    assert states["mysql"].docker_health == "healthy"
    assert warnings == []


def test_build_runtime_states_unhealthy():
    containers = [_container("mysql", service_label="mysql", status="Up 1 hour (unhealthy)")]
    states, _ = build_runtime_states({"mysql"}, containers)
    assert states["mysql"].docker_health == "unhealthy"


def test_build_runtime_states_starting():
    containers = [_container("mysql", service_label="mysql", status="Up 10 seconds (health: starting)")]
    states, _ = build_runtime_states({"mysql"}, containers)
    assert states["mysql"].docker_health == "starting"


def test_build_runtime_states_running_no_healthcheck():
    containers = [_container("mysql", service_label="mysql", status="Up 3 hours")]
    states, _ = build_runtime_states({"mysql"}, containers)
    assert states["mysql"].running is True
    assert states["mysql"].docker_health is None


def test_build_runtime_states_stopped():
    containers = [_container("mysql", service_label="mysql", status="Exited (0) 2 hours ago")]
    states, _ = build_runtime_states({"mysql"}, containers)
    assert states["mysql"].present is True
    assert states["mysql"].running is False


def test_build_runtime_states_missing_service_stays_unknown():
    states, _ = build_runtime_states({"mysql"}, [])
    assert states["mysql"] is _NO_RUNTIME_STATE


def test_build_runtime_states_empty_status_string():
    containers = [_container("mysql", service_label="mysql", status="")]
    states, _ = build_runtime_states({"mysql"}, containers)
    assert states["mysql"].running is None
    assert states["mysql"].docker_health is None


def test_build_runtime_states_docker_unavailable_is_none_containers():
    states, warnings = build_runtime_states({"mysql", "redis"}, None)
    assert all(s is _NO_RUNTIME_STATE for s in states.values())
    assert warnings == []


def test_runtime_state_never_includes_container_id():
    containers = [_container("mysql", service_label="mysql")]
    containers[0]["ID"] = "abc123deadbeef"
    states, _ = build_runtime_states({"mysql"}, containers)
    payload = json.dumps(states["mysql"].to_public_dict())
    assert "abc123deadbeef" not in payload


# ---------------------------------------------------------------------------
# Intrinsic health precedence
# ---------------------------------------------------------------------------


def test_intrinsic_health_application_probe_up():
    health, evidence = intrinsic_health("x", {"status": "UP"}, _NO_RUNTIME_STATE)
    assert health is RuntimeHealth.HEALTHY
    assert evidence.source is EvidenceSource.HTTP_PROBE


def test_intrinsic_health_application_probe_warn():
    health, _ = intrinsic_health("x", {"status": "WARN"}, _NO_RUNTIME_STATE)
    assert health is RuntimeHealth.DEGRADED


def test_intrinsic_health_application_probe_down():
    health, _ = intrinsic_health("x", {"status": "DOWN"}, _NO_RUNTIME_STATE)
    assert health is RuntimeHealth.UNHEALTHY


def test_intrinsic_health_probe_wins_over_docker_healthcheck():
    runtime = RuntimeState(present=True, running=True, docker_health="unhealthy", image_raw=None, match_evidence=None)
    health, evidence = intrinsic_health("x", {"status": "UP"}, runtime)
    assert health is RuntimeHealth.HEALTHY
    assert evidence.source is EvidenceSource.HTTP_PROBE


def test_intrinsic_health_docker_healthcheck_when_no_probe():
    runtime = RuntimeState(present=True, running=True, docker_health="healthy", image_raw=None, match_evidence=None)
    health, evidence = intrinsic_health("x", None, runtime)
    assert health is RuntimeHealth.HEALTHY
    assert evidence.source is EvidenceSource.DOCKER_INSPECT


def test_intrinsic_health_docker_healthcheck_unhealthy():
    runtime = RuntimeState(present=True, running=True, docker_health="unhealthy", image_raw=None, match_evidence=None)
    health, _ = intrinsic_health("x", None, runtime)
    assert health is RuntimeHealth.UNHEALTHY


def test_intrinsic_health_docker_healthcheck_starting_is_unknown():
    runtime = RuntimeState(present=True, running=True, docker_health="starting", image_raw=None, match_evidence=None)
    health, evidence = intrinsic_health("x", None, runtime)
    assert health is RuntimeHealth.UNKNOWN
    assert evidence.source is EvidenceSource.DOCKER_INSPECT


def test_intrinsic_health_running_without_healthcheck_is_unknown_not_healthy():
    # CONTAINER RUNNING != SERVICE HEALTHY
    runtime = RuntimeState(present=True, running=True, docker_health=None, image_raw=None, match_evidence=None)
    health, _ = intrinsic_health("x", None, runtime)
    assert health is RuntimeHealth.UNKNOWN


def test_intrinsic_health_stopped_container_is_unhealthy():
    runtime = RuntimeState(present=True, running=False, docker_health=None, image_raw=None, match_evidence=None)
    health, _ = intrinsic_health("x", None, runtime)
    assert health is RuntimeHealth.UNHEALTHY


def test_intrinsic_health_no_evidence_is_unknown():
    health, _ = intrinsic_health("x", None, _NO_RUNTIME_STATE)
    assert health is RuntimeHealth.UNKNOWN


def test_intrinsic_health_unrecognized_probe_status_falls_through():
    runtime = RuntimeState(present=True, running=True, docker_health="healthy", image_raw=None, match_evidence=None)
    health, evidence = intrinsic_health("x", {"status": "WEIRD"}, runtime)
    assert health is RuntimeHealth.HEALTHY
    assert evidence.source is EvidenceSource.DOCKER_INSPECT


# ---------------------------------------------------------------------------
# Dependency-aware effective health
# ---------------------------------------------------------------------------


def test_effective_health_intrinsic_unhealthy_ignores_dependencies():
    health, _ = effective_health(
        "a", RuntimeHealth.UNHEALTHY,
        [("b", DependencyRelationship.HARD)],
        {"b": RuntimeHealth.HEALTHY},
    )
    assert health is RuntimeHealth.UNHEALTHY


def test_effective_health_hard_dependency_unhealthy_degrades_healthy_intrinsic():
    # TES/ToolServer example from the brief.
    health, evidence = effective_health(
        "tes", RuntimeHealth.HEALTHY,
        [("toolserver", DependencyRelationship.HARD)],
        {"toolserver": RuntimeHealth.UNHEALTHY},
    )
    assert health is RuntimeHealth.DEGRADED
    assert any("toolserver" in e.detail for e in evidence)


def test_effective_health_soft_dependency_failure_does_not_degrade():
    health, evidence = effective_health(
        "a", RuntimeHealth.HEALTHY,
        [("b", DependencyRelationship.SOFT)],
        {"b": RuntimeHealth.UNHEALTHY},
    )
    assert health is RuntimeHealth.HEALTHY
    assert any("soft dependency" in e.detail for e in evidence)


def test_effective_health_hard_dependency_unknown_degrades():
    health, _ = effective_health(
        "a", RuntimeHealth.HEALTHY,
        [("b", DependencyRelationship.HARD)],
        {"b": RuntimeHealth.UNKNOWN},
    )
    assert health is RuntimeHealth.DEGRADED


def test_effective_health_no_bad_dependencies_stays_intrinsic():
    health, evidence = effective_health(
        "a", RuntimeHealth.HEALTHY,
        [("b", DependencyRelationship.HARD)],
        {"b": RuntimeHealth.HEALTHY},
    )
    assert health is RuntimeHealth.HEALTHY
    assert evidence == ()


def test_effective_health_intrinsic_unknown_no_bad_hard_deps_stays_unknown():
    health, _ = effective_health("a", RuntimeHealth.UNKNOWN, [], {})
    assert health is RuntimeHealth.UNKNOWN


def test_effective_health_intrinsic_unknown_with_hard_unhealthy_becomes_degraded():
    health, _ = effective_health(
        "a", RuntimeHealth.UNKNOWN,
        [("b", DependencyRelationship.HARD)],
        {"b": RuntimeHealth.UNHEALTHY},
    )
    assert health is RuntimeHealth.DEGRADED


def test_effective_health_never_escalates_degraded_to_unhealthy_from_dependency():
    health, _ = effective_health(
        "a", RuntimeHealth.DEGRADED,
        [("b", DependencyRelationship.HARD)],
        {"b": RuntimeHealth.UNHEALTHY},
    )
    assert health is RuntimeHealth.DEGRADED


def test_effective_health_dependency_cycle_does_not_hang_or_recurse():
    # A <-> B, both HARD. Only intrinsic values are consulted (one-hop),
    # so a cycle is not a special case at all -- this simply terminates.
    intrinsic_by_service = {"a": RuntimeHealth.HEALTHY, "b": RuntimeHealth.UNHEALTHY}
    health_a, _ = effective_health("a", RuntimeHealth.HEALTHY, [("b", DependencyRelationship.HARD)], intrinsic_by_service)
    health_b, _ = effective_health("b", RuntimeHealth.UNHEALTHY, [("a", DependencyRelationship.HARD)], intrinsic_by_service)
    assert health_a is RuntimeHealth.DEGRADED  # a's own intrinsic is fine, b is down
    assert health_b is RuntimeHealth.UNHEALTHY  # b's own intrinsic already failed


def test_effective_health_missing_dependency_target_is_treated_as_unknown():
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
    configured = parse_image_reference("mysql:8.0")
    status, c, r = compare_image(configured, "mysql:8.0")
    assert status.value == "match"
    assert c == "mysql:8.0" and r == "mysql:8.0"


def test_compare_image_match_with_registry_normalization():
    configured = parse_image_reference("mysql:8.0")
    status, _, _ = compare_image(configured, "docker.io/library/mysql:8.0")
    assert status.value == "match"


def test_compare_image_mismatch_tag():
    configured = parse_image_reference("mysql:8.0")
    status, _, _ = compare_image(configured, "mysql:5.7")
    assert status.value == "mismatch"


def test_compare_image_mismatch_repository():
    configured = parse_image_reference("mysql:8.0")
    status, _, _ = compare_image(configured, "postgres:8.0")
    assert status.value == "mismatch"


def test_compare_image_unknown_when_missing():
    status, c, r = compare_image(None, "mysql:8.0")
    assert status.value == "unknown"
    assert c is None and r is None


def test_compare_image_unknown_when_configured_has_variable():
    configured = parse_image_reference("mysql:${TAG}")
    status, _, _ = compare_image(configured, "mysql:8.0")
    assert status.value == "unknown"


def test_compare_image_unknown_when_either_side_untagged():
    configured = parse_image_reference("mysql")
    status, _, _ = compare_image(configured, "mysql:8.0")
    assert status.value == "unknown"


def test_compare_image_unknown_when_either_side_latest():
    configured = parse_image_reference("mysql:latest")
    status, _, _ = compare_image(configured, "mysql:latest")
    assert status.value == "unknown"  # "latest" is never a verified match


def test_compare_image_unknown_when_running_has_variable():
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
    return parse_compose_text(_COMPOSE, baseline_source=BaselineSource.DEVELOPMENT)


def test_summary_counts_are_dynamic_not_hardcoded():
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
    inventory = _inventory()
    response = build_deployment_health_response(
        inventory, generated_at="2026-08-30T12:34:56+00:00",
        containers=[], probe_results={},
        prometheus_availability=SourceAvailability.NOT_CONFIGURED,
        regression_context={"availability": "unavailable", "phases": None, "freshness": None},
    )
    assert response["generated_at"] == "2026-08-30T12:34:56+00:00"


def test_warnings_merge_compose_and_runtime_warnings():
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
