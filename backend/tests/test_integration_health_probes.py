"""tests/test_integration_health_probes.py -- control_center.
integration_health_probes: P0ProbeRunner's live-probe execution against
the allowlisted P0 integrations (HTTPS-only, excluding the known-unsafe
P0_UNSUPPORTED set), normalizing every transport/HTTP/schema failure mode
into a (ProviderStatus, FailureReason, ReadinessStatus) triple, honoring
a rate-limit Retry-After cooldown via JsonProbeCache (skipping the
provider entirely until it elapses), bounding concurrency, isolating one
probe's failure from the rest, and redacting any secret/raw-payload field
before it's ever written to the cache file on disk.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""
from datetime import UTC, datetime, timedelta
from threading import Lock
from time import sleep

import httpx
import pytest
from control_center.integration_health import (
    FailureReason,
    ProviderStatus,
    ReadinessStatus,
)
from control_center.integration_health_probes import (
    P0_PROBE_DEFINITIONS,
    P0_UNSUPPORTED,
    JsonProbeCache,
    P0ProbeRunner,
    ProbeResponse,
)

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)


def payload_for(integration_id):
    """The expected well-formed success-response body for a given P0
    integration id."""
    return {
        "ncbi": {"header": {}}, "clinvar": {"header": {}}, "pubchem": {"PropertyTable": {}},
        "ensembl": {"ping": 1}, "uniprot": {"primaryAccession": "P04637"},
        "rcsb_pdb": {"rcsb_id": "4HHB"}, "reactome": "87",
    }[integration_id]


class FakeTransport:
    """A fake probe transport that returns a canned/exception response per
    integration_id (defaulting to a well-formed success payload), tracks
    concurrent call count, and can inject a fixed per-call delay to
    exercise concurrency bounding."""

    def __init__(self, responses=None, delay=0):
        self.responses = responses or {}
        self.delay = delay
        self.calls = []
        self.active = 0
        self.max_active = 0
        self.lock = Lock()

    def get(self, definition):
        with self.lock:
            self.calls.append((definition.integration_id, definition.endpoint))
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                sleep(self.delay)
            response = self.responses.get(definition.integration_id)
            if isinstance(response, BaseException):
                raise response
            return response or ProbeResponse(200, {"content-type": "application/json"}, payload_for(definition.integration_id))
        finally:
            with self.lock:
                self.active -= 1


def response(status=200, payload=None, headers=None):
    """A ProbeResponse with sensible content-type-header defaults."""
    return ProbeResponse(status, headers or {"content-type": "application/json"}, payload)


def test_allowlist_is_static_https_and_excludes_unsafe_p0s():
    """P0_PROBE_DEFINITIONS is exactly the 7 known-safe P0 integrations,
    P0_UNSUPPORTED is exactly the 3 known-unsafe ones, and every
    allowlisted probe endpoint uses HTTPS."""
    assert {definition.integration_id for definition in P0_PROBE_DEFINITIONS} == {
        "ncbi", "pubchem", "ensembl", "clinvar", "uniprot", "reactome", "rcsb_pdb",
    }
    assert set(P0_UNSUPPORTED) == {"gnomad", "opentargets", "string_db"}
    assert all(definition.endpoint.startswith("https://") for definition in P0_PROBE_DEFINITIONS)


def test_all_successful_probes_are_cached_as_normalized_results(tmp_path):
    """Every allowlisted probe succeeding is reported AVAILABLE/READY,
    written to the cache with exactly the documented field set, and the
    unsupported set is still reported alongside the results."""
    transport = FakeTransport()
    cache = JsonProbeCache(tmp_path / "readiness.json")
    summary = P0ProbeRunner(transport=transport, cache=cache).run(now=NOW)
    assert len(summary.results) == 7
    assert all(result.provider_status is ProviderStatus.AVAILABLE for result in summary.results)
    assert all(result.readiness_status is ReadinessStatus.READY for result in summary.results)
    assert set(cache.get("ncbi")) == {"provider_status", "checked_at", "failure_reason", "description"}
    assert set(summary.unsupported) == set(P0_UNSUPPORTED)
    assert all(url.startswith("https://") for _, url in transport.calls)


@pytest.mark.parametrize(("fake", "status", "failure", "readiness"), [
    (httpx.ReadTimeout("timeout"), ProviderStatus.UNAVAILABLE, FailureReason.TIMEOUT, ReadinessStatus.NOT_READY),
    (httpx.ConnectError("dns"), ProviderStatus.UNAVAILABLE, FailureReason.DNS, ReadinessStatus.NOT_READY),
    (httpx.NetworkError("network"), ProviderStatus.UNAVAILABLE, FailureReason.NETWORK, ReadinessStatus.NOT_READY),
])
def test_transport_failures_are_normalized(fake, status, failure, readiness):
    """A raw transport-level exception (timeout/DNS/network) is
    normalized to the matching (ProviderStatus, FailureReason,
    ReadinessStatus) triple."""
    transport = FakeTransport({"ncbi": fake})
    result = P0ProbeRunner(transport=transport, definitions=P0_PROBE_DEFINITIONS[:1]).run(now=NOW).results[0]
    assert (result.provider_status, result.failure_reason, result.readiness_status) == (status, failure, readiness)


@pytest.mark.parametrize(("probe_response", "failure", "status", "readiness"), [
    (response(401, {}), FailureReason.AUTHENTICATION, ProviderStatus.UNAVAILABLE, ReadinessStatus.NOT_READY),
    (response(403, {}), FailureReason.AUTHORIZATION, ProviderStatus.UNAVAILABLE, ReadinessStatus.NOT_READY),
    (response(429, {}, {"Retry-After": "42"}), FailureReason.RATE_LIMIT, ProviderStatus.DEGRADED, ReadinessStatus.DEGRADED),
    (response(503, {}), FailureReason.PROVIDER_5XX, ProviderStatus.UNAVAILABLE, ReadinessStatus.NOT_READY),
    (response(200, {"wrong": True}), FailureReason.SCHEMA_MISMATCH, ProviderStatus.UNAVAILABLE, ReadinessStatus.NOT_READY),
])
def test_http_and_schema_failures_are_normalized(probe_response, failure, status, readiness):
    """Each recognized HTTP status (401/403/429/503) and an unexpected-
    shape 200 body all normalize to the matching (FailureReason,
    ProviderStatus, ReadinessStatus) triple, with 429 specifically
    classified DEGRADED rather than fully UNAVAILABLE."""
    transport = FakeTransport({"ncbi": probe_response})
    result = P0ProbeRunner(transport=transport, definitions=P0_PROBE_DEFINITIONS[:1]).run(now=NOW).results[0]
    assert (result.provider_status, result.failure_reason, result.readiness_status) == (status, failure, readiness)


def test_rate_limit_retry_after_is_persisted_as_next_eligible(tmp_path):
    """A 429 with Retry-After: 42 persists next_eligible_at as `now +
    42s`, and a run before that time elapses skips the provider entirely
    (skipped_cooldown) rather than re-probing it."""
    cache = JsonProbeCache(tmp_path / "cache.json")
    transport = FakeTransport({"ncbi": response(429, {}, {"Retry-After": "42"})})
    result = P0ProbeRunner(transport=transport, cache=cache, definitions=P0_PROBE_DEFINITIONS[:1]).run(now=NOW).results[0]
    assert result.retry_after_seconds == 42
    assert cache.get("ncbi")["next_eligible_at"] == "2026-08-30T12:00:42Z"
    skipped = P0ProbeRunner(transport=transport, cache=cache, definitions=P0_PROBE_DEFINITIONS[:1]).run(now=NOW + timedelta(seconds=41))
    assert skipped.results == ()
    assert skipped.skipped_cooldown == ("ncbi",)


def test_cooldown_uses_cached_result_and_does_not_call_provider(tmp_path):
    """A pre-populated, still-fresh cache entry causes the runner to
    skip that provider without making any transport call at all."""
    cache = JsonProbeCache(tmp_path / "cache.json")
    cache.set("ncbi", {"provider_status": "AVAILABLE", "checked_at": "2026-08-30T11:59:00Z"})
    transport = FakeTransport()
    summary = P0ProbeRunner(transport=transport, cache=cache, definitions=P0_PROBE_DEFINITIONS[:1]).run(now=NOW)
    assert summary.results == ()
    assert summary.skipped_cooldown == ("ncbi",)
    assert transport.calls == []


def test_failures_are_isolated_and_concurrency_is_bounded():
    """One provider's failure (ncbi's 503) doesn't stop the rest of the
    P0 set from being probed and reported, and the runner never exceeds
    a small fixed concurrency cap."""
    transport = FakeTransport({"ncbi": response(503, {})}, delay=0.001)
    summary = P0ProbeRunner(transport=transport, definitions=P0_PROBE_DEFINITIONS).run(now=NOW)
    assert {result.integration_id for result in summary.results} == {d.integration_id for d in P0_PROBE_DEFINITIONS}
    assert next(result for result in summary.results if result.integration_id == "ncbi").provider_status is ProviderStatus.UNAVAILABLE
    assert transport.max_active <= 4


def test_cache_redacts_unexpected_fields_and_never_stores_payload(tmp_path):
    """Setting a cache entry containing a raw_payload or an Authorization-
    looking secret field never writes those values to disk -- the JSON
    cache file on disk contains neither."""
    path = tmp_path / "cache.json"
    cache = JsonProbeCache(path)
    cache.set("ncbi", {"provider_status": "AVAILABLE", "raw_payload": {"token": "secret"}, "Authorization": "Bearer secret"})
    raw = path.read_text()
    assert "secret" not in raw
    assert "raw_payload" not in raw
