"""Route-level tests for GET /deployment-health: safe 503 responses when the compose
file is unconfigured, missing or invalid, the response shape and data-source reporting,
Docker image drift wiring, the permission dependency, configuration helpers and route
registration. Docker, settings, Prometheus and regression-health inputs are patched, and
compose files are written to temporary directories.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from control_center.api.routes_deployment_health import (
    _baseline_source,
    _load_probe_results,
    _local_image_ids,
    _regression_context,
    get_deployment_health,
)
from control_center.core.auth import require_permission
from control_center.deployment_health import BaselineSource, parse_compose_text
from control_center.main import app
from control_center.regression_health import RegressionHealthUnavailable

_VALID_COMPOSE = """
services:
  mysql:
    image: mysql:8.0
  auth-service:
    image: ghcr.io/omnibioai/omnibioai-auth:latest
    depends_on:
      mysql:
        condition: service_healthy
"""


def _write_compose(directory: str, text: str = _VALID_COMPOSE) -> str:
    """Writes the given compose text (a two-service mysql and auth-service file by
    default) to docker-compose.yml in the directory and returns its path."""
    path = Path(directory) / "docker-compose.yml"
    path.write_text(text, encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# Compose failure semantics (section 15)
# ---------------------------------------------------------------------------


class ComposeFailureTestCase(unittest.IsolatedAsyncioTestCase):
    """get_deployment_health() when the compose file is unconfigured, missing or
    invalid: each case returns a safe 503 payload."""
    async def test_unconfigured_compose_path_returns_safe_unavailable(self) -> None:
        """With DEPLOYMENT_HEALTH_COMPOSE_PATH unset, the endpoint returns 503 with the
        fixed STATUS_UNAVAILABLE payload."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEPLOYMENT_HEALTH_COMPOSE_PATH", None)
            response = await get_deployment_health()
        assert response.status_code == 503
        assert json.loads(response.body) == {
            "status": "STATUS_UNAVAILABLE",
            "message": "Deployment health data is unavailable.",
        }

    async def test_missing_compose_file_returns_safe_unavailable_no_path_leak(self) -> None:
        """A nonexistent compose path returns 503, and the response body does not
        contain the configured path."""
        with patch.dict(os.environ, {"DEPLOYMENT_HEALTH_COMPOSE_PATH": "/nonexistent/very/private/path.yml"}):
            response = await get_deployment_health()
        assert response.status_code == 503
        assert b"/nonexistent/very/private/path" not in response.body

    async def test_invalid_yaml_returns_safe_unavailable(self) -> None:
        """A compose file containing invalid YAML returns 503."""
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_compose(tmp, "services: [this is not: valid: yaml: -")
            with patch.dict(os.environ, {"DEPLOYMENT_HEALTH_COMPOSE_PATH": path}):
                response = await get_deployment_health()
        assert response.status_code == 503


# ---------------------------------------------------------------------------
# Valid endpoint response / dynamic behavior (section 27)
# ---------------------------------------------------------------------------


class ValidResponseTestCase(unittest.IsolatedAsyncioTestCase):
    """get_deployment_health() with a valid temporary compose file and patched Docker,
    settings, Prometheus and regression-health inputs: response shape and data-source
    availability."""
    async def test_valid_compose_returns_200_with_expected_shape(self) -> None:
        """A valid compose file returns 200 with a total of 2 services (mysql and
        auth-service), Docker reported available, and application_probe and
        regression_health reported unavailable."""
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_compose(tmp)
            with patch.dict(os.environ, {"DEPLOYMENT_HEALTH_COMPOSE_PATH": path}), \
                 patch("control_center.api.routes_deployment_health.get_containers_status",
                       return_value={"containers": [], "running": 0, "stopped": 0}), \
                 patch("control_center.api.routes_deployment_health.load_settings",
                       side_effect=FileNotFoundError()), \
                 patch("control_center.api.routes_deployment_health.load_regression_health",
                       side_effect=RegressionHealthUnavailable("artifact_missing")):
                response = await get_deployment_health()

        assert response.status_code == 200
        body = json.loads(response.body)
        assert body["summary"]["total"] == 2
        assert {s["service_id"] for s in body["services"]} == {"mysql", "auth-service"}
        assert body["data_sources"]["docker"] == "available"
        assert body["data_sources"]["application_probe"] == "unavailable"
        assert body["data_sources"]["regression_health"] == "unavailable"

    async def test_prometheus_not_configured_reflected(self) -> None:
        """With Prometheus not configured and Docker reporting an error, data_sources
        shows prometheus not_configured and docker unavailable, every service's
        intrinsic health is unknown, and the endpoint still returns 200."""
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_compose(tmp)
            with patch.dict(os.environ, {"DEPLOYMENT_HEALTH_COMPOSE_PATH": path}), \
                 patch("control_center.api.routes_deployment_health.get_containers_status",
                       return_value={"error": "docker not found", "containers": []}), \
                 patch("control_center.api.routes_deployment_health.load_settings",
                       side_effect=FileNotFoundError()), \
                 patch("control_center.analytics.prometheus.is_configured", return_value=False):
                response = await get_deployment_health()

        body = json.loads(response.body)
        assert body["data_sources"]["prometheus"] == "not_configured"
        assert body["data_sources"]["docker"] == "unavailable"
        # Docker unavailable never fails the whole endpoint.
        assert response.status_code == 200
        for service in body["services"]:
            assert service["health"]["intrinsic"] == "unknown"

    async def test_prometheus_configured_but_unreachable(self) -> None:
        """With Prometheus configured but its instant query reporting unavailable,
        data_sources.prometheus is unavailable."""
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_compose(tmp)
            with patch.dict(os.environ, {"DEPLOYMENT_HEALTH_COMPOSE_PATH": path}), \
                 patch("control_center.api.routes_deployment_health.get_containers_status",
                       return_value={"containers": [], "running": 0, "stopped": 0}), \
                 patch("control_center.api.routes_deployment_health.load_settings",
                       side_effect=FileNotFoundError()), \
                 patch("control_center.analytics.prometheus.is_configured", return_value=True), \
                 patch("control_center.analytics.prometheus.instant_query",
                       new=AsyncMock(return_value={"available": False, "result": None})):
                response = await get_deployment_health()

        body = json.loads(response.body)
        assert body["data_sources"]["prometheus"] == "unavailable"

    async def test_generated_at_present(self) -> None:
        """The response body includes a non-empty generated_at."""
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_compose(tmp)
            with patch.dict(os.environ, {"DEPLOYMENT_HEALTH_COMPOSE_PATH": path}), \
                 patch("control_center.api.routes_deployment_health.get_containers_status",
                       return_value={"containers": [], "running": 0, "stopped": 0}), \
                 patch("control_center.api.routes_deployment_health.load_settings",
                       side_effect=FileNotFoundError()):
                response = await get_deployment_health()
        body = json.loads(response.body)
        assert body["generated_at"]


# ---------------------------------------------------------------------------
# DH-5: drift wiring at the route layer (section 27)
# ---------------------------------------------------------------------------


class DriftIntegrationTestCase(unittest.IsolatedAsyncioTestCase):
    """Drift wiring at the route layer: the drift and drift_summary fields, and how
    local image ids feed each service's drift status."""
    async def test_response_shape_includes_drift_and_drift_summary(self) -> None:
        """The response carries a drift_summary with match, drifted, unknown and
        not_applicable counts, and every service has a drift entry with source,
        configured, running and drift."""
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_compose(tmp)
            with patch.dict(os.environ, {"DEPLOYMENT_HEALTH_COMPOSE_PATH": path}), \
                 patch("control_center.api.routes_deployment_health.get_containers_status",
                       return_value={"containers": [], "running": 0, "stopped": 0}), \
                 patch("control_center.api.routes_deployment_health.get_local_image_ids",
                       return_value={}), \
                 patch("control_center.api.routes_deployment_health.load_settings",
                       side_effect=FileNotFoundError()), \
                 patch("control_center.api.routes_deployment_health.load_regression_health",
                       side_effect=RegressionHealthUnavailable("artifact_missing")):
                response = await get_deployment_health()

        body = json.loads(response.body)
        assert "drift_summary" in body
        assert set(body["drift_summary"]) == {"match", "drifted", "unknown", "not_applicable"}
        for service in body["services"]:
            assert "drift" in service
            assert set(service["drift"]) == {"source", "configured", "running", "drift"}

    async def test_docker_unavailable_never_calls_get_local_image_ids(self) -> None:
        """When Docker is unavailable, get_local_image_ids is never called; mysql, with
        no OmniBioAI ownership evidence, is not_applicable and auth-service is unknown
        rather than a fabricated match."""
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_compose(tmp)
            with patch.dict(os.environ, {"DEPLOYMENT_HEALTH_COMPOSE_PATH": path}), \
                 patch("control_center.api.routes_deployment_health.get_containers_status",
                       return_value={"error": "docker not found", "containers": []}), \
                 patch("control_center.api.routes_deployment_health.get_local_image_ids") as mock_local_ids, \
                 patch("control_center.api.routes_deployment_health.load_settings",
                       side_effect=FileNotFoundError()):
                response = await get_deployment_health()

        mock_local_ids.assert_not_called()
        body = json.loads(response.body)
        assert response.status_code == 200
        by_id = {s["service_id"]: s for s in body["services"]}
        # mysql has no OmniBioAI repository ownership evidence -> not_applicable;
        # auth-service is OmniBioAI-owned but Docker is unavailable -> unknown,
        # never a fabricated match.
        assert by_id["mysql"]["drift"]["drift"]["status"] == "not_applicable"
        assert by_id["auth-service"]["drift"]["drift"]["status"] == "unknown"

    async def test_matching_local_image_id_produces_match_end_to_end(self) -> None:
        """When the running container's image id equals the local image id for
        auth-service's image, its drift status is match and drift_summary.match is 1."""
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_compose(tmp)
            containers = [{
                "Names": "auth-1",
                "Status": "Up 3 hours",
                "Image": "ghcr.io/omnibioai/omnibioai-auth:latest",
                "Labels": "com.docker.compose.service=auth-service,"
                          "com.docker.compose.image=sha256:abc123",
            }]
            with patch.dict(os.environ, {"DEPLOYMENT_HEALTH_COMPOSE_PATH": path}), \
                 patch("control_center.api.routes_deployment_health.get_containers_status",
                       return_value={"containers": containers, "running": 1, "stopped": 0}), \
                 patch("control_center.api.routes_deployment_health.get_local_image_ids",
                       return_value={"ghcr.io/omnibioai/omnibioai-auth:latest": "sha256:abc123"}) as mock_local_ids, \
                 patch("control_center.api.routes_deployment_health.load_settings",
                       side_effect=FileNotFoundError()):
                response = await get_deployment_health()

        mock_local_ids.assert_called_once()
        body = json.loads(response.body)
        by_id = {s["service_id"]: s for s in body["services"]}
        assert by_id["auth-service"]["drift"]["drift"]["status"] == "match"
        assert body["drift_summary"]["match"] == 1


class LocalImageIdsHelperTestCase(unittest.TestCase):
    """_local_image_ids() resolves the compose image references through
    get_local_image_ids only when Docker is available."""
    def _inventory(self):
        return parse_compose_text(_VALID_COMPOSE, baseline_source=BaselineSource.UNKNOWN)

    def test_docker_unavailable_short_circuits_without_a_call(self) -> None:
        """With docker_available False, no lookup is made and an empty dict is returned."""
        with patch("control_center.api.routes_deployment_health.get_local_image_ids") as mock_local_ids:
            result = _local_image_ids(self._inventory(), docker_available=False)
        mock_local_ids.assert_not_called()
        assert result == {}

    def test_docker_available_delegates_to_get_local_image_ids(self) -> None:
        """With Docker available, get_local_image_ids is called once with every compose
        image reference (including mysql:8.0 and the auth image) and its result is
        returned."""
        with patch("control_center.api.routes_deployment_health.get_local_image_ids",
                    return_value={"mysql:8.0": "sha256:xyz"}) as mock_local_ids:
            result = _local_image_ids(self._inventory(), docker_available=True)
        mock_local_ids.assert_called_once()
        (called_refs,), _ = mock_local_ids.call_args
        assert "mysql:8.0" in called_refs
        assert "ghcr.io/omnibioai/omnibioai-auth:latest" in called_refs
        assert result == {"mysql:8.0": "sha256:xyz"}


# ---------------------------------------------------------------------------
# Authorization (section 26)
# ---------------------------------------------------------------------------


def test_unauthenticated_request_is_401() -> None:
    """The platform.manage_infra permission dependency raises HTTP 401 when no
    Authorization header is supplied."""
    dependency = require_permission("platform.manage_infra")
    with pytest.raises(HTTPException) as error:
        dependency(None)
    assert error.value.status_code == 401


def test_authenticated_without_permission_is_403() -> None:
    """A token with no permissions makes the platform.manage_infra dependency raise HTTP
    403."""
    dependency = require_permission("platform.manage_infra")
    with patch("control_center.core.auth.verify_token", return_value={"permissions": []}), \
         pytest.raises(HTTPException) as error:
        dependency("Bearer test-token")
    assert error.value.status_code == 403


def test_authorized_dependency_grants_access() -> None:
    """A token carrying platform.manage_infra passes the dependency and its payload is
    returned."""
    dependency = require_permission("platform.manage_infra")
    with patch("control_center.core.auth.verify_token",
               return_value={"permissions": ["platform.manage_infra"]}):
        payload = dependency("Bearer test-token")
    assert payload["permissions"] == ["platform.manage_infra"]


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def test_baseline_source_invalid_value_falls_back_to_unknown() -> None:
    """An unrecognized DEPLOYMENT_HEALTH_BASELINE_SOURCE value falls back to
    BaselineSource.UNKNOWN."""
    with patch.dict(os.environ, {"DEPLOYMENT_HEALTH_BASELINE_SOURCE": "not-a-real-source"}):
        assert _baseline_source() is BaselineSource.UNKNOWN


def test_baseline_source_unset_is_unknown() -> None:
    """With DEPLOYMENT_HEALTH_BASELINE_SOURCE unset, the baseline source is
    BaselineSource.UNKNOWN."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("DEPLOYMENT_HEALTH_BASELINE_SOURCE", None)
        assert _baseline_source() is BaselineSource.UNKNOWN


def test_baseline_source_valid_value() -> None:
    """DEPLOYMENT_HEALTH_BASELINE_SOURCE set to release yields BaselineSource.RELEASE."""
    with patch.dict(os.environ, {"DEPLOYMENT_HEALTH_BASELINE_SOURCE": "release"}):
        assert _baseline_source() is BaselineSource.RELEASE


def test_load_probe_results_success_keyed_by_service_name() -> None:
    """_load_probe_results returns the run_all_checks results keyed by service name."""
    fake_results = [{"name": "mysql", "status": "UP"}, {"name": "redis", "status": "DOWN"}]
    with patch("control_center.api.routes_deployment_health.load_settings", return_value=object()), \
         patch("control_center.api.routes_deployment_health.run_all_checks", return_value=fake_results):
        results = _load_probe_results()
    assert results == {"mysql": {"name": "mysql", "status": "UP"}, "redis": {"name": "redis", "status": "DOWN"}}


def test_load_probe_results_unexpected_exception_degrades_to_none() -> None:
    """An unexpected exception from run_all_checks makes _load_probe_results return None
    instead of raising."""
    with patch("control_center.api.routes_deployment_health.load_settings", return_value=object()), \
         patch("control_center.api.routes_deployment_health.run_all_checks", side_effect=RuntimeError("boom")):
        assert _load_probe_results() is None


def test_regression_context_available_path_is_compact() -> None:
    """_regression_context reports availability available with each phase's status and
    certification_status and the freshness status, and leaves out the capabilities list."""
    fake_data = {
        "phases": {
            "p0": {"status": "complete", "certification_status": "certified"},
            "p1": {"status": "in_progress", "certification_status": "partial"},
        },
        "capabilities": [{"id": "should-not-appear"}],
        "freshness": {"status": "CURRENT"},
    }
    with patch("control_center.api.routes_deployment_health.load_regression_health", return_value=fake_data):
        context = _regression_context()
    assert context["availability"] == "available"
    assert context["phases"] == {
        "p0": {"status": "complete", "certification_status": "certified"},
        "p1": {"status": "in_progress", "certification_status": "partial"},
    }
    assert "capabilities" not in context
    assert context["freshness"] == {"status": "CURRENT"}


# ---------------------------------------------------------------------------
# Route registration / read-only verification (sections 25, 27)
# ---------------------------------------------------------------------------


def test_route_is_registered() -> None:
    """The app registers a /deployment-health route."""
    assert any(route.path == "/deployment-health" for route in app.routes)


def test_route_is_get_only() -> None:
    """Every /deployment-health route accepts only the GET method."""
    matching = [route for route in app.routes if getattr(route, "path", None) == "/deployment-health"]
    assert matching, "route not found"
    for route in matching:
        assert route.methods == {"GET"}


def test_route_requires_manage_infra_permission() -> None:
    """The /deployment-health route's dependencies include a require_permission
    dependency; the specific permission is not asserted here."""
    matching = [route for route in app.routes if getattr(route, "path", None) == "/deployment-health"]
    assert matching
    route = matching[0]
    dependant_names = {dep.call.__qualname__ for dep in route.dependant.dependencies}
    assert any("require_permission" in name for name in dependant_names)
