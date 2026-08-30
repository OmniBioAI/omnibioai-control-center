"""Read and validate the promoted OmniBioAI regression status artifact.

This module is a consumer of the RH-1 contract.  It does not infer
certification from test output and it never exposes the configured filesystem
location through the API.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SUPPORTED_SCHEMA_VERSION = "1.0"
DEFAULT_STALE_AFTER_HOURS = 168.0
DEFAULT_ARTIFACT_RELATIVE_PATH = Path(
    "omnibioai-ecosystem-regression/status/regression-health.json"
)

_STATUS_VALUES = {
    "complete", "in_progress", "implemented", "not_implemented", "pass",
    "certified", "partial", "paused", "blocked", "not_run",
    "not_certified", "failed", "unknown",
}
_FINDING_STATUS_VALUES = {"fixed", "open", "closed", "unknown"}
_VALIDATION_STATUS_VALUES = {"tested", "live_validated", "not_live_validated", "unknown"}
_REQUIRED_TOP_LEVEL = {"schema_version", "generated_at", "source", "phases",
                       "capabilities", "findings", "technical_debt"}
_SENSITIVE_KEYS = {
    "credential", "credentials", "password", "secret", "secrets", "token",
    "tokens", "jwt", "handle", "backend_handle", "container_id", "job_id",
    "username", "user_name", "filesystem_path", "absolute_path",
}


class RegressionHealthUnavailable(ValueError):
    """Raised when the promoted artifact cannot safely be consumed."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def artifact_path() -> Path:
    """Return the configured artifact path without exposing it to callers."""
    configured = os.environ.get("REGRESSION_HEALTH_ARTIFACT_PATH")
    if configured:
        return Path(configured)
    workspace = Path(os.environ.get("WORKSPACE_ROOT", "/workspace"))
    return workspace / DEFAULT_ARTIFACT_RELATIVE_PATH


def stale_after_hours() -> float:
    configured = os.environ.get("REGRESSION_HEALTH_STALE_AFTER_HOURS")
    if not configured:
        return DEFAULT_STALE_AFTER_HOURS
    try:
        value = float(configured)
    except ValueError:
        return DEFAULT_STALE_AFTER_HOURS
    return value if value > 0 else DEFAULT_STALE_AFTER_HOURS


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise RegressionHealthUnavailable(code)


def _validate_safe_values(value: Any, key: str | None = None) -> None:
    lowered_key = key.lower() if key else ""
    if key and (
        lowered_key in _SENSITIVE_KEYS
        or any(marker in lowered_key for marker in ("secret", "token", "password", "credential", "private_key"))
    ):
        raise RegressionHealthUnavailable("sensitive_field")
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            _validate_safe_values(child_value, str(child_key))
    elif isinstance(value, list):
        for item in value:
            _validate_safe_values(item)
    elif isinstance(value, str):
        lowered = value.lower()
        if value.startswith(("/", "\\")) or "-----begin " in lowered:
            raise RegressionHealthUnavailable("sensitive_value")
        if any(marker in lowered for marker in ("bearer ", "eyj", "password=", "token=", "secret=")):
            raise RegressionHealthUnavailable("sensitive_value")


def _validate_artifact(data: Any) -> dict[str, Any]:
    _require(isinstance(data, dict), "root_not_object")
    _require(_REQUIRED_TOP_LEVEL <= data.keys(), "required_field")
    _require(data.get("schema_version") == SUPPORTED_SCHEMA_VERSION, "unsupported_schema")
    _require(isinstance(data.get("generated_at"), str) and bool(data["generated_at"]),
             "generated_at")

    source = data["source"]
    _require(isinstance(source, dict), "source")
    _require(source.get("repository") == "omnibioai-ecosystem-regression", "source_repository")
    _require(isinstance(source.get("commit"), str) and bool(source["commit"]), "source_commit")
    if "workflow_run_id" in source:
        _require(source["workflow_run_id"] is None or isinstance(source["workflow_run_id"], str),
                 "workflow_run_id")

    phases = data["phases"]
    _require(isinstance(phases, dict) and set(phases) == {"p0", "p1", "p2"}, "phases")
    for phase in phases.values():
        _require(isinstance(phase, dict), "phase")
        _require(phase.get("status") in {"complete", "in_progress", "partial", "blocked", "unknown"},
                 "phase_status")
        _require(phase.get("certification_status") in _STATUS_VALUES, "phase_certification_status")
        _require("evidence" in phase and isinstance(phase["evidence"], dict), "phase_evidence")

    capabilities = data["capabilities"]
    _require(isinstance(capabilities, list), "capabilities")
    for capability in capabilities:
        _require(isinstance(capability, dict), "capability")
        for field in ("id", "label", "implementation_status", "test_status", "live_status",
                      "certification_status", "evidence"):
            _require(field in capability, "capability_field")
        _require(isinstance(capability["id"], str) and isinstance(capability["label"], str),
                 "capability_identity")
        for field in ("implementation_status", "test_status", "live_status", "certification_status"):
            _require(capability[field] in _STATUS_VALUES, "capability_status")
        _require(isinstance(capability["evidence"], dict), "capability_evidence")

    findings = data["findings"]
    _require(isinstance(findings, list), "findings")
    for finding in findings:
        _require(isinstance(finding, dict), "finding")
        for field in ("id", "status", "validation_status", "summary"):
            _require(field in finding, "finding_field")
        _require(isinstance(finding["id"], str), "finding_id")
        _require(finding["status"] in _FINDING_STATUS_VALUES, "finding_status")
        _require(finding["validation_status"] in _VALIDATION_STATUS_VALUES, "validation_status")
        _require(isinstance(finding["summary"], str), "finding_summary")

    _require(isinstance(data["technical_debt"], list), "technical_debt")
    _validate_safe_values(data)
    return data


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _freshness(generated_at: str, now: datetime | None = None) -> dict[str, Any]:
    timestamp = _parse_timestamp(generated_at)
    threshold = stale_after_hours()
    if timestamp is None:
        return {"status": "UNKNOWN", "stale_after_hours": threshold}
    current_time = now or datetime.now(UTC)
    age_seconds = max(0.0, (current_time - timestamp).total_seconds())
    return {
        "status": "STALE" if age_seconds > threshold * 3600 else "CURRENT",
        "age_seconds": round(age_seconds, 3),
        "stale_after_hours": threshold,
    }


def load_regression_health(*, now: datetime | None = None) -> dict[str, Any]:
    """Load RH-1 data and add only derived Control Center freshness metadata."""
    path = artifact_path()
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        code = "artifact_missing" if isinstance(exc, FileNotFoundError) else "artifact_unreadable"
        raise RegressionHealthUnavailable(code) from None

    validated = _validate_artifact(data)
    response = deepcopy(validated)
    response["freshness"] = _freshness(validated["generated_at"], now=now)
    return response
