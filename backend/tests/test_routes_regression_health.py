from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from control_center.api.routes_regression_health import get_regression_health
from control_center.core.auth import require_permission
from control_center.main import app
from control_center.regression_health import (
    RegressionHealthUnavailable,
    load_regression_health,
)


def _artifact(*, generated_at: str = "2026-08-29T12:00:00Z") -> dict:
    statuses = {
        "local-nextflow": ("Local Nextflow", "pass", "pass", "certified"),
        "slurm-tes": ("Slurm/TES", "pass", "pass", "certified"),
        "gateway-routing": ("Gateway routing / REG-007", "pass", "pass", "certified"),
        "slurm-result-transport": ("Slurm result transport / REG-008", "pass", "pass", "certified"),
        "local-cancellation": ("Local cancellation", "pass", "pass", "certified"),
        "slurm-cancellation": ("Slurm cancellation", "pass", "pass", "certified"),
        "cancellation-races": ("Cancellation race handling / REG-009", "pass", "pass", "certified"),
        "tenant-isolation": ("Tenant isolation", "pass", "pass", "certified"),
        "audit-correlation": ("Audit correlation", "pass", "partial", "partial"),
        "backend-aware-timeout": ("Backend-aware timeout", "pass", "paused", "not_certified"),
        "bounded-concurrency": ("Bounded concurrency", "not_run", "not_run", "not_certified"),
        "gpu": ("GPU", "not_run", "blocked", "not_certified"),
        "wdl": ("WDL", "not_run", "not_run", "not_certified"),
        "snakemake": ("Snakemake", "not_run", "not_run", "not_certified"),
        "cwl": ("CWL", "not_run", "not_run", "not_certified"),
        "kubernetes": ("Kubernetes", "not_run", "blocked", "not_certified"),
        "aws-batch": ("AWS Batch", "not_run", "blocked", "not_certified"),
        "azure-batch": ("Azure Batch", "not_run", "blocked", "not_certified"),
    }
    return {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "source": {"repository": "omnibioai-ecosystem-regression", "commit": "abc123"},
        "phases": {
            "p0": {"status": "complete", "certification_status": "certified", "evidence": {}},
            "p1": {"status": "complete", "certification_status": "certified", "evidence": {}},
            "p2": {"status": "in_progress", "certification_status": "partial", "evidence": {}},
        },
        "capabilities": [
            {"id": key, "label": value[0], "implementation_status": "implemented",
             "test_status": value[1], "live_status": value[2],
             "certification_status": value[3], "evidence": {}}
            for key, value in statuses.items()
        ],
        "findings": [
            {"id": f"REG-00{number}", "status": "fixed", "validation_status": "live_validated",
             "summary": f"Finding REG-00{number} is fixed."}
            for number in (7, 8, 9)
        ],
        "technical_debt": [{"id": "phase-6-4-pause", "status": "paused", "summary": "Live timeout certification is paused."}],
    }


def _write_artifact(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "regression-health.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_valid_artifact_preserves_phases_capabilities_and_findings(tmp_path: Path) -> None:
    path = _write_artifact(tmp_path, _artifact())
    with patch.dict(os.environ, {"REGRESSION_HEALTH_ARTIFACT_PATH": str(path), "REGRESSION_HEALTH_STALE_AFTER_HOURS": "168"}):
        result = load_regression_health(now=datetime(2026, 8, 29, 13, tzinfo=UTC))
    assert result["schema_version"] == "1.0"
    assert result["phases"]["p0"]["certification_status"] == "certified"
    assert result["phases"]["p1"]["status"] == "complete"
    assert result["phases"]["p2"]["status"] == "in_progress"
    by_id = {item["id"]: item for item in result["capabilities"]}
    assert by_id["backend-aware-timeout"]["certification_status"] == "not_certified"
    assert {item["id"] for item in result["findings"]} == {"REG-007", "REG-008", "REG-009"}
    assert result["freshness"]["status"] == "CURRENT"


def test_old_artifact_is_stale_without_mutating_certification(tmp_path: Path) -> None:
    path = _write_artifact(tmp_path, _artifact(generated_at="2026-08-20T12:00:00Z"))
    with patch.dict(os.environ, {"REGRESSION_HEALTH_ARTIFACT_PATH": str(path), "REGRESSION_HEALTH_STALE_AFTER_HOURS": "24"}):
        result = load_regression_health(now=datetime(2026, 8, 29, 12, tzinfo=UTC))
    assert result["freshness"]["status"] == "STALE"
    assert result["phases"]["p0"]["certification_status"] == "certified"


def test_invalid_timestamp_is_unknown(tmp_path: Path) -> None:
    path = _write_artifact(tmp_path, _artifact(generated_at="not-a-timestamp"))
    with patch.dict(os.environ, {"REGRESSION_HEALTH_ARTIFACT_PATH": str(path)}):
        result = load_regression_health()
    assert result["freshness"]["status"] == "UNKNOWN"


@pytest.mark.parametrize("mutator", [
    lambda data: data.update(schema_version="9.0"),
    lambda data: data.pop("phases"),
    lambda data: data["capabilities"][0].update(certification_status="surprise"),
    lambda data: data["findings"][0].update(status="surprise"),
    lambda data: data.update(password="do-not-accept"),
    lambda data: data["technical_debt"].append({"summary": "/internal/absolute/path"}),
])
def test_invalid_or_unsafe_artifact_is_unavailable(tmp_path: Path, mutator) -> None:
    data = _artifact()
    mutator(data)
    path = _write_artifact(tmp_path, data)
    with patch.dict(os.environ, {"REGRESSION_HEALTH_ARTIFACT_PATH": str(path)}), pytest.raises(RegressionHealthUnavailable):
        load_regression_health()


@pytest.mark.parametrize("content", ["not json", "{}"])
def test_missing_or_malformed_artifact_is_unavailable(tmp_path: Path, content: str) -> None:
    path = tmp_path / "regression-health.json"
    path.write_text(content, encoding="utf-8")
    with patch.dict(os.environ, {"REGRESSION_HEALTH_ARTIFACT_PATH": str(path)}), pytest.raises(RegressionHealthUnavailable):
        load_regression_health()


def test_endpoint_requires_manage_infra_and_returns_safe_unavailable(tmp_path: Path) -> None:
    missing = tmp_path / "missing" / "regression-health.json"
    with patch.dict(os.environ, {"REGRESSION_HEALTH_ARTIFACT_PATH": str(missing)}):
        response = get_regression_health()
    assert response.status_code == 503
    assert json.loads(response.body) == {
        "status": "STATUS_UNAVAILABLE",
        "message": "Regression health certification data is unavailable.",
    }
    assert b"missing" not in response.body

    dependency = require_permission("platform.manage_infra")
    with pytest.raises(HTTPException) as error:
        dependency(None)
    assert error.value.status_code == 401


def test_authorized_dependency_and_endpoint_succeed(tmp_path: Path) -> None:
    path = _write_artifact(tmp_path, _artifact())
    dependency = require_permission("platform.manage_infra")
    with patch("control_center.core.auth.verify_token", return_value={"permissions": ["platform.manage_infra"]}):
        assert dependency("Bearer test-token")["permissions"] == ["platform.manage_infra"]
    with patch.dict(os.environ, {"REGRESSION_HEALTH_ARTIFACT_PATH": str(path)}):
        assert get_regression_health().status_code == 200


def test_endpoint_denies_valid_token_without_permission() -> None:
    dependency = require_permission("platform.manage_infra")
    with patch("control_center.core.auth.verify_token", return_value={"permissions": []}), pytest.raises(HTTPException) as error:
        dependency("Bearer test-token")
    assert error.value.status_code == 403


def test_route_is_registered() -> None:
    assert any(route.path == "/regression-health" for route in app.routes)
