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
    _regression_context,
    get_deployment_health,
)
from control_center.core.auth import require_permission
from control_center.deployment_health import BaselineSource
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
    path = Path(directory) / "docker-compose.yml"
    path.write_text(text, encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# Compose failure semantics (section 15)
# ---------------------------------------------------------------------------


class ComposeFailureTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_unconfigured_compose_path_returns_safe_unavailable(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEPLOYMENT_HEALTH_COMPOSE_PATH", None)
            response = await get_deployment_health()
        assert response.status_code == 503
        assert json.loads(response.body) == {
            "status": "STATUS_UNAVAILABLE",
            "message": "Deployment health data is unavailable.",
        }

    async def test_missing_compose_file_returns_safe_unavailable_no_path_leak(self) -> None:
        with patch.dict(os.environ, {"DEPLOYMENT_HEALTH_COMPOSE_PATH": "/nonexistent/very/private/path.yml"}):
            response = await get_deployment_health()
        assert response.status_code == 503
        assert b"/nonexistent/very/private/path" not in response.body

    async def test_invalid_yaml_returns_safe_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_compose(tmp, "services: [this is not: valid: yaml: -")
            with patch.dict(os.environ, {"DEPLOYMENT_HEALTH_COMPOSE_PATH": path}):
                response = await get_deployment_health()
        assert response.status_code == 503


# ---------------------------------------------------------------------------
# Valid endpoint response / dynamic behavior (section 27)
# ---------------------------------------------------------------------------


class ValidResponseTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_valid_compose_returns_200_with_expected_shape(self) -> None:
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
# Authorization (section 26)
# ---------------------------------------------------------------------------


def test_unauthenticated_request_is_401() -> None:
    dependency = require_permission("platform.manage_infra")
    with pytest.raises(HTTPException) as error:
        dependency(None)
    assert error.value.status_code == 401


def test_authenticated_without_permission_is_403() -> None:
    dependency = require_permission("platform.manage_infra")
    with patch("control_center.core.auth.verify_token", return_value={"permissions": []}), \
         pytest.raises(HTTPException) as error:
        dependency("Bearer test-token")
    assert error.value.status_code == 403


def test_authorized_dependency_grants_access() -> None:
    dependency = require_permission("platform.manage_infra")
    with patch("control_center.core.auth.verify_token",
               return_value={"permissions": ["platform.manage_infra"]}):
        payload = dependency("Bearer test-token")
    assert payload["permissions"] == ["platform.manage_infra"]


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def test_baseline_source_invalid_value_falls_back_to_unknown() -> None:
    with patch.dict(os.environ, {"DEPLOYMENT_HEALTH_BASELINE_SOURCE": "not-a-real-source"}):
        assert _baseline_source() is BaselineSource.UNKNOWN


def test_baseline_source_unset_is_unknown() -> None:
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("DEPLOYMENT_HEALTH_BASELINE_SOURCE", None)
        assert _baseline_source() is BaselineSource.UNKNOWN


def test_baseline_source_valid_value() -> None:
    with patch.dict(os.environ, {"DEPLOYMENT_HEALTH_BASELINE_SOURCE": "release"}):
        assert _baseline_source() is BaselineSource.RELEASE


def test_load_probe_results_success_keyed_by_service_name() -> None:
    fake_results = [{"name": "mysql", "status": "UP"}, {"name": "redis", "status": "DOWN"}]
    with patch("control_center.api.routes_deployment_health.load_settings", return_value=object()), \
         patch("control_center.api.routes_deployment_health.run_all_checks", return_value=fake_results):
        results = _load_probe_results()
    assert results == {"mysql": {"name": "mysql", "status": "UP"}, "redis": {"name": "redis", "status": "DOWN"}}


def test_load_probe_results_unexpected_exception_degrades_to_none() -> None:
    with patch("control_center.api.routes_deployment_health.load_settings", return_value=object()), \
         patch("control_center.api.routes_deployment_health.run_all_checks", side_effect=RuntimeError("boom")):
        assert _load_probe_results() is None


def test_regression_context_available_path_is_compact() -> None:
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
    assert any(route.path == "/deployment-health" for route in app.routes)


def test_route_is_get_only() -> None:
    matching = [route for route in app.routes if getattr(route, "path", None) == "/deployment-health"]
    assert matching, "route not found"
    for route in matching:
        assert route.methods == {"GET"}


def test_route_requires_manage_infra_permission() -> None:
    matching = [route for route in app.routes if getattr(route, "path", None) == "/deployment-health"]
    assert matching
    route = matching[0]
    dependant_names = {dep.call.__qualname__ for dep in route.dependant.dependencies}
    assert any("require_permission" in name for name in dependant_names)
