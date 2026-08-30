"""DH-2: read-only `GET /deployment-health`.

Combines DH-1's static Compose inventory (`control_center.deployment_health`)
with existing runtime/probe/monitoring sources -- reusing them, never
reimplementing:

- Docker container state: `routes_docker.get_containers_status()`, the
  same subprocess call `routes_dashboard.py`'s aggregator already reuses.
- Application-level health: `core.runner.run_all_checks`, the same
  function `GET /services` and `GET /summary` already expose, keyed by
  the same service_id as Compose.
- Regression Health: `regression_health.load_regression_health()`, reduced
  to a compact global context here -- never mapped to individual services
  (RH is capability-oriented, not per-service; see DH-2 docs).
- Prometheus: `analytics.prometheus`, the existing client. Compact
  top-level availability only -- no per-service target correlation exists
  in this deployment to report (no scrape config anywhere in this
  workspace as of DH-2; see DH-2 docs for why this is deferred, not
  skipped by omission).

Only Compose/DH-1 failing makes this endpoint fail (503,
`STATUS_UNAVAILABLE`, matching regression_health.py's own safe-failure
shape). Every other source degrading (Docker down, probe config missing,
Prometheus/Regression Health unavailable) is reflected in the response's
`data_sources` block, never a fatal error -- see
`deployment_health_runtime.build_deployment_health_response`, which does
the actual assembly as a pure, testable function.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from control_center.analytics import prometheus as prometheus_client
from control_center.api.routes_docker import get_containers_status, get_local_image_ids
from control_center.core.runner import run_all_checks
from control_center.core.settings import load_settings
from control_center.deployment_health import (
    BaselineSource,
    DeploymentHealthUnavailable,
    DeploymentInventory,
    load_compose_file,
)
from control_center.deployment_health_drift import image_refs_to_inspect
from control_center.deployment_health_runtime import (
    SourceAvailability,
    build_deployment_health_response,
)
from control_center.regression_health import (
    RegressionHealthUnavailable,
    load_regression_health,
)

router = APIRouter()
log = logging.getLogger(__name__)


def _compose_path() -> str | None:
    return os.environ.get("DEPLOYMENT_HEALTH_COMPOSE_PATH") or None


def _baseline_source() -> BaselineSource:
    raw = (os.environ.get("DEPLOYMENT_HEALTH_BASELINE_SOURCE") or "").strip().lower()
    try:
        return BaselineSource(raw) if raw else BaselineSource.UNKNOWN
    except ValueError:
        return BaselineSource.UNKNOWN


def _deployment_repository() -> str | None:
    return os.environ.get("DEPLOYMENT_HEALTH_DEPLOYMENT_REPOSITORY") or None


def _unavailable_response() -> JSONResponse:
    return JSONResponse(
        {
            "status": "STATUS_UNAVAILABLE",
            "message": "Deployment health data is unavailable.",
        },
        status_code=503,
    )


def _load_probe_results() -> dict[str, dict] | None:
    """None means the application-probe config itself couldn't be loaded
    -- distinct from a config that loads but has nothing configured for a
    given service. This is an optional data source: any failure here
    degrades `data_sources.application_probe`, never the whole endpoint."""
    try:
        settings = load_settings()
        results = run_all_checks(settings)
    except FileNotFoundError:
        return None
    except Exception:
        log.warning("Deployment health: application-probe collection failed", exc_info=True)
        return None
    return {result["name"]: result for result in results}


def _docker_containers() -> list[dict] | None:
    """None means Docker itself is unavailable -- `get_containers_status`
    never raises (see routes_docker.py), it reports `{"error": ...}`."""
    status = get_containers_status()
    if "error" in status:
        return None
    return status.get("containers", [])


def _local_image_ids(inventory: DeploymentInventory, docker_available: bool) -> dict[str, str]:
    """DH-5: one bounded, deduplicated `docker image inspect` call for
    this inventory's own known configured image references. Never called
    at all when Docker is already known to be unavailable (same
    `docker` CLI path would just fail again); `get_local_image_ids`
    itself never raises either way, so a failure here only ever degrades
    every service's drift to UNKNOWN, never the whole endpoint."""
    if not docker_available:
        return {}
    refs = image_refs_to_inspect(list(inventory.services))
    return get_local_image_ids(refs)


async def _prometheus_availability() -> SourceAvailability:
    if not prometheus_client.is_configured():
        return SourceAvailability.NOT_CONFIGURED
    result = await prometheus_client.instant_query("up")
    return SourceAvailability.AVAILABLE if result.get("available") else SourceAvailability.UNAVAILABLE


def _regression_context() -> dict:
    """Compact global context only -- id/status/certification_status per
    phase and freshness. Never the full artifact (capabilities/findings/
    technical_debt), and never mapped to an individual service: RH is
    capability-oriented, not per-service certification (DH-1 discovery)."""
    try:
        data = load_regression_health()
    except RegressionHealthUnavailable:
        return {"availability": SourceAvailability.UNAVAILABLE.value, "phases": None, "freshness": None}

    phases = {
        phase_id: {
            "status": phase["status"],
            "certification_status": phase["certification_status"],
        }
        for phase_id, phase in data["phases"].items()
    }
    return {
        "availability": SourceAvailability.AVAILABLE.value,
        "phases": phases,
        "freshness": data["freshness"],
    }


@router.get("/deployment-health")
async def get_deployment_health() -> JSONResponse:
    compose_path = _compose_path()
    if not compose_path:
        log.warning("Deployment health status unavailable: compose_path_not_configured")
        return _unavailable_response()

    try:
        inventory = load_compose_file(
            compose_path,
            baseline_source=_baseline_source(),
            deployment_repository=_deployment_repository(),
        )
    except DeploymentHealthUnavailable as error:
        # Deliberately not accompanied by the path or the underlying
        # exception, which could disclose deployment information (same
        # convention as routes_regression_health.py).
        log.warning("Deployment health status unavailable: %s", error.code)
        return _unavailable_response()

    containers = _docker_containers()
    response = build_deployment_health_response(
        inventory,
        generated_at=datetime.now(UTC).isoformat(),
        containers=containers,
        probe_results=_load_probe_results(),
        prometheus_availability=await _prometheus_availability(),
        regression_context=_regression_context(),
        local_image_ids=_local_image_ids(inventory, docker_available=containers is not None),
    )
    return JSONResponse(response)
