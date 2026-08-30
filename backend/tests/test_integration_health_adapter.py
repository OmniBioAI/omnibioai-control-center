import json
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from control_center.api.routes_integration_health import get_integration_health
from control_center.core.auth import require_permission
from control_center.integration_health import (
    AuthRequirement,
    EnabledStatus,
    ProviderStatus,
    ReadinessStatus,
)
from control_center.integration_health_adapter import (
    IntegrationInventoryUnavailable,
    JsonReadinessCache,
    WorkbenchIntegrationAdapter,
    build_integration_health_report,
)
from control_center.main import app
from control_center.regression_health import RegressionHealthUnavailable
from fastapi import HTTPException


def _manifest(slug: str, category: str = "reference_db", enabled: bool = True) -> dict:
    return {"slug": slug, "name": slug.title(), "category": category, "enabled": enabled, "version": "1.0.0"}


def _fixture(tmp_path, count: int = 3):
    root = tmp_path / "plugins"
    root.mkdir()
    manifests = []
    for index in range(count):
        slug = f"provider_{index}"
        plugin = root / slug
        plugin.mkdir()
        (plugin / "client.py").write_text(
            "def health_check(client):\n    return {'status': 'ok'}\n" if index == 0
            else "def health_live(request):\n    return None\n" if index == 1 else "def run():\n    return None\n",
            encoding="utf-8",
        )
        manifests.append(_manifest(slug, enabled=index != 2))
    registry = tmp_path / "plugin_registry.json"
    registry.write_text(json.dumps(manifests), encoding="utf-8")
    return root, registry


def test_adapter_dynamically_builds_inventory_and_excludes_non_biological(tmp_path):
    root, registry = _fixture(tmp_path)
    payload = json.loads(registry.read_text()) + [_manifest("workflow", "pipeline")]
    registry.write_text(json.dumps(payload), encoding="utf-8")
    records = WorkbenchIntegrationAdapter(registry_path=registry, plugins_dir=root).build().records
    assert [record.integration_id for record in records] == ["provider_0", "provider_1", "provider_2"]
    assert records[0].probe_availability.value == "READY_SIGNAL_EXISTS"
    assert records[1].probe_availability.value == "PLUGIN_LIVENESS_ONLY"
    assert records[2].enabled_status is EnabledStatus.DISABLED
    assert records[2].readiness() is ReadinessStatus.DISABLED


def test_real_shape_compatibility_fixture_has_dynamic_67_and_49_10_8(tmp_path):
    root = tmp_path / "plugins"
    root.mkdir()
    manifests = []
    for index in range(67):
        slug = f"integration_{index}"
        plugin = root / slug
        plugin.mkdir()
        marker = "health_check" if index < 49 else "health_live" if index < 59 else "noop"
        (plugin / "client.py").write_text(f"def {marker}(): pass\n", encoding="utf-8")
        manifests.append(_manifest(slug))
    registry = tmp_path / "plugin_registry.json"
    registry.write_text(json.dumps(manifests), encoding="utf-8")
    records = WorkbenchIntegrationAdapter(registry_path=registry, plugins_dir=root).build().records
    assert len(records) == 67
    assert sum(record.probe_availability.value == "READY_SIGNAL_EXISTS" for record in records) == 49
    assert sum(record.probe_availability.value == "PLUGIN_LIVENESS_ONLY" for record in records) == 10
    assert sum(record.probe_availability.value == "NO_SAFE_READINESS_SIGNAL" for record in records) == 8


def test_duplicate_id_is_safe_error(tmp_path):
    root, registry = _fixture(tmp_path)
    registry.write_text(json.dumps([_manifest("same"), _manifest("same")]), encoding="utf-8")
    with patch.object(WorkbenchIntegrationAdapter, "_record", return_value=None):
        try:
            WorkbenchIntegrationAdapter(registry_path=registry, plugins_dir=root).build()
        except IntegrationInventoryUnavailable as error:
            assert error.code == "duplicate_integration_id"
        else:
            raise AssertionError("duplicate ids must not overwrite")


def test_cached_ready_degraded_and_unknown_are_read_only(tmp_path):
    root, registry = _fixture(tmp_path)
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps({"provider_0": {
        "provider_status": "AVAILABLE", "checked_at": "2026-08-30T10:00:00Z", "version": "release-x",
    }, "provider_1": {"provider_status": "DEGRADED", "failure_reason": "RATE_LIMIT"}}), encoding="utf-8")
    cache = JsonReadinessCache(cache_path)
    records = WorkbenchIntegrationAdapter(
        registry_path=registry,
        plugins_dir=root,
        configuration={
            "provider_0": {"configuration_status": "NOT_REQUIRED", "auth_requirement": "PUBLIC"},
            "provider_1": {"configuration_status": "NOT_REQUIRED", "auth_requirement": "PUBLIC"},
        },
        readiness_cache=cache,
    ).build().records
    assert records[0].provider.status is ProviderStatus.AVAILABLE
    assert records[0].readiness() is ReadinessStatus.READY
    assert records[0].provider.version == "release-x"
    assert records[1].readiness() is ReadinessStatus.DEGRADED
    assert records[2].provider.status is ProviderStatus.NOT_CHECKED
    assert records[2].readiness() is ReadinessStatus.DISABLED


def test_configuration_metadata_is_allowlisted(tmp_path, monkeypatch):
    root, registry = _fixture(tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"provider_0": {
        "auth_requirement": "AUTH_REQUIRED", "configuration_status": "CONFIGURED",
        "credential_configured": True, "token": "must-not-be-read",
    }}), encoding="utf-8")
    monkeypatch.setenv("INTEGRATION_HEALTH_CONFIGURATION_PATH", str(config_path))
    payload = build_integration_health_report(
        adapter=WorkbenchIntegrationAdapter(registry_path=registry, plugins_dir=root),
        generated_at=datetime(2026, 8, 30, tzinfo=UTC),
    )
    item = next(entry for entry in payload["integrations"] if entry["integration_id"] == "provider_0")
    assert item["authentication"] == {"requirement": AuthRequirement.AUTH_REQUIRED.value, "credential_configured": True}
    assert "must-not-be-read" not in json.dumps(payload)
    assert payload["data_sources"]["configuration"] == "AVAILABLE"


def test_invalid_registry_and_safe_route_503(tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("WORKBENCH_PLUGIN_REGISTRY_PATH", str(bad))
    with patch("control_center.api.routes_integration_health.build_integration_health_report",
               side_effect=IntegrationInventoryUnavailable("registry_invalid")):
        response = get_integration_health()
    assert response.status_code == 503
    assert response.body == b'{"status":"STATUS_UNAVAILABLE","message":"Integration health data is unavailable."}'
    assert str(bad) not in response.body.decode()


def test_invalid_optional_cache_is_non_fatal(tmp_path, monkeypatch):
    root, registry = _fixture(tmp_path)
    monkeypatch.setenv("WORKBENCH_PLUGIN_REGISTRY_PATH", str(registry))
    monkeypatch.setenv("WORKBENCH_PLUGINS_DIR", str(root))
    monkeypatch.setenv("INTEGRATION_HEALTH_READINESS_CACHE_PATH", str(tmp_path / "missing-cache.json"))
    payload = build_integration_health_report(generated_at=datetime(2026, 8, 30, tzinfo=UTC))
    assert payload["data_sources"]["readiness_cache"] == "UNAVAILABLE"
    assert payload["summary"]["unknown"] == 2


def test_regression_health_source_failure_is_unavailable(tmp_path, monkeypatch):
    root, registry = _fixture(tmp_path)
    monkeypatch.setenv("WORKBENCH_PLUGIN_REGISTRY_PATH", str(registry))
    monkeypatch.setenv("WORKBENCH_PLUGINS_DIR", str(root))
    with patch(
        "control_center.regression_health.load_regression_health",
        side_effect=RegressionHealthUnavailable("artifact_missing"),
    ):
        payload = build_integration_health_report(
            adapter=WorkbenchIntegrationAdapter(registry_path=registry, plugins_dir=root),
            generated_at=datetime(2026, 8, 30, tzinfo=UTC),
        )
    assert payload["data_sources"]["regression_health"] == "UNAVAILABLE"


def test_protected_route_authentication(tmp_path, monkeypatch):
    root, registry = _fixture(tmp_path)
    monkeypatch.setenv("WORKBENCH_PLUGIN_REGISTRY_PATH", str(registry))
    monkeypatch.setenv("WORKBENCH_PLUGINS_DIR", str(root))
    dependency = require_permission("platform.manage_infra")
    with patch("control_center.core.auth.verify_token", return_value={"permissions": ["platform.manage_infra"]}):
        assert dependency("Bearer test-token")["permissions"] == ["platform.manage_infra"]
    with patch("control_center.core.auth.verify_token", return_value={"permissions": []}):
        with pytest.raises(HTTPException) as error:
            dependency("Bearer test-token")
        assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        dependency(None)
    assert error.value.status_code == 401
    assert any(route.path == "/integration-health" for route in app.routes)


def test_route_is_get_only():
    assert not any(route.path == "/integration-health" and "POST" in route.methods for route in app.routes)
