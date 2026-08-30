from datetime import UTC, datetime, timedelta

import pytest
from control_center.integration_health import (
    AuthRequirement,
    ConfigurationStatus,
    DataSourceStatus,
    EnabledStatus,
    EvidenceType,
    FailureReason,
    Freshness,
    ImplementationStatus,
    IntegrationEvidence,
    IntegrationInventory,
    IntegrationProvider,
    IntegrationRecord,
    ProbeAvailability,
    ProviderStatus,
    ReadinessStatus,
)

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)


def record(**overrides):
    values = {
        "integration_id": "pubchem", "display_name": "PubChem", "provider": IntegrationProvider(
            "NCBI", "REST", "PUG-REST", ProviderStatus.AVAILABLE, NOW,
        ), "category": "DRUG_CHEMISTRY", "plugin": "pubchem", "enabled_status": EnabledStatus.ENABLED,
        "configuration_status": ConfigurationStatus.NOT_REQUIRED, "auth_requirement": AuthRequirement.PUBLIC,
        "probe_availability": ProbeAvailability.READY_SIGNAL_EXISTS,
    }
    values.update(overrides)
    return IntegrationRecord(**values)


@pytest.mark.parametrize(("kwargs", "expected"), [
    ({}, ReadinessStatus.READY),
    ({"provider": IntegrationProvider("NCBI", "REST", status=ProviderStatus.DEGRADED,
                                       failure_reason=FailureReason.RATE_LIMIT)}, ReadinessStatus.DEGRADED),
    ({"provider": IntegrationProvider("NCBI", "REST", status=ProviderStatus.UNAVAILABLE,
                                       failure_reason=FailureReason.TIMEOUT)}, ReadinessStatus.NOT_READY),
    ({"provider": IntegrationProvider("NCBI", "REST")}, ReadinessStatus.UNKNOWN),
    ({"enabled_status": EnabledStatus.DISABLED}, ReadinessStatus.DISABLED),
    ({"implementation_status": ImplementationStatus.NOT_IMPLEMENTED}, ReadinessStatus.NOT_READY),
    ({"auth_requirement": AuthRequirement.AUTH_REQUIRED,
      "configuration_status": ConfigurationStatus.NOT_CONFIGURED}, ReadinessStatus.NOT_READY),
    ({"configuration_status": ConfigurationStatus.UNKNOWN}, ReadinessStatus.READY),
    ({"configuration_status": ConfigurationStatus.UNKNOWN,
      "provider": IntegrationProvider("NCBI", "REST")}, ReadinessStatus.UNKNOWN),
    ({"configuration_status": ConfigurationStatus.UNKNOWN,
      "provider": IntegrationProvider("NCBI", "REST", status=ProviderStatus.AVAILABLE)}, ReadinessStatus.READY),
])
def test_readiness_rules(kwargs, expected):
    assert record(**kwargs).readiness() is expected


def test_auth_metadata_never_contains_credential_value():
    item = record(auth_requirement=AuthRequirement.AUTH_REQUIRED, credential_configured=True)
    payload = item.to_public_dict(now=NOW)
    assert payload["authentication"] == {"requirement": "AUTH_REQUIRED", "credential_configured": True}


def test_freshness_and_unknown_timestamp():
    assert record().to_public_dict(now=NOW)["freshness"] == Freshness.CURRENT.value
    old = record(provider=IntegrationProvider("NCBI", "REST", last_checked=NOW - timedelta(hours=2)))
    assert old.to_public_dict(now=NOW)["freshness"] == Freshness.STALE.value
    assert record(provider=IntegrationProvider("NCBI", "REST")).to_public_dict(now=NOW)["freshness"] == Freshness.UNKNOWN.value


def test_summary_is_deterministic_and_counts_all_states():
    records = (record(), record(provider=IntegrationProvider("X", "REST", status=ProviderStatus.DEGRADED)),
               record(enabled_status=EnabledStatus.DISABLED), record(provider=IntegrationProvider("X", "REST")),
               record(implementation_status=ImplementationStatus.NOT_IMPLEMENTED))
    assert IntegrationInventory(records).summary().to_public_dict() == {
        "total": 5, "ready": 1, "degraded": 1, "not_ready": 1, "disabled": 1, "unknown": 1,
    }


def test_evidence_types_and_safe_serialization():
    item = record(evidence=(IntegrationEvidence(EvidenceType.LIVE_PROBE, "PASS",
                                                 "token=abc /srv/control-center", NOW),),
                   warnings=("Authorization: Bearer eyJabcdefghijk",))
    raw = str(item.to_public_dict(now=NOW))
    assert "abc" not in raw and "eyJabcdefghijk" not in raw and "/srv/control-center" not in raw
    assert item.to_public_dict(now=NOW)["evidence"][0]["source"] == "LIVE_PROBE"


def test_invalid_failure_combination_rejected():
    with pytest.raises(ValueError):
        IntegrationProvider("X", "REST", status=ProviderStatus.AVAILABLE, failure_reason=FailureReason.NETWORK)


def test_public_shape_has_no_raw_provider_payload_or_paths():
    payload = IntegrationInventory((record(),), {"plugin_registry": DataSourceStatus.AVAILABLE}).to_public_dict(generated_at=NOW)
    assert set(payload) == {"schema_version", "generated_at", "summary", "integrations", "data_sources", "warnings"}
    assert "http" not in str(payload["integrations"][0]["provider"])
