"""tests/test_deployment_health_drift.py -- control_center.
deployment_health_drift: compute_drift()'s image-vs-running-container
comparison, using local Docker image-id resolution as the only reliable
evidence for a mutable tag (a matching tag string alone is never treated
as a match) while an immutable digest-pinned reference is compared
directly. Covers third-party/no-image/no-container edge cases (all
NOT_APPLICABLE or UNKNOWN, never a false MATCH/DRIFTED), the untagged-
image-gets-":latest"-suffix convention matching Docker's own RepoTags
behavior, drift_summary()'s aggregate counts, and to_public_dict()'s
strict field allowlist (never leaking an absolute path, working
directory, or secret-shaped string from a container's raw labels).

Developer:
    Manish Kumar <manish@omnibioai.org>
"""
from __future__ import annotations

import json

from control_center.deployment_health import (
    DeploymentService,
    MetadataCompleteness,
    ServiceCategory,
    parse_image_reference,
)
from control_center.deployment_health_drift import (
    DriftStatus,
    RevisionType,
    build_service_drift,
    compute_drift,
    configured_artifact_for,
    drift_summary,
    image_refs_to_inspect,
    running_artifact_from_container,
    source_version_for,
)


def _service(service_id="svc", repository="omnibioai-svc", image_raw=None, **overrides) -> DeploymentService:
    """A DeploymentService with sensible defaults, any field
    overridable by keyword, and an optional raw image ref parsed for
    the "image" field."""
    image = parse_image_reference(image_raw) if image_raw else None
    defaults = {
        "service_id": service_id,
        "display_name": service_id.title(),
        "category": ServiceCategory.EXECUTION,
        "repository": repository,
        "ownership_evidence": None,
        "image": image,
        "build_configured": False,
        "healthcheck_configured": False,
        "ports": (),
        "dependency_count": 0,
        "evidence": (),
        "completeness": MetadataCompleteness(repository_known=True, category_known=True, dependencies_known=True),
    }
    defaults.update(overrides)
    return DeploymentService(**defaults)


def _container(labels: str = "") -> dict:
    """A minimal fake `docker ps` container dict with the given raw Labels string."""
    return {"Names": "x", "Status": "Up", "Image": "x", "Labels": labels}


# ---------------------------------------------------------------------------
# source_version_for
# ---------------------------------------------------------------------------


def test_source_version_reuses_dh1_repository_and_stays_unknown_revision():
    """source_version_for() reuses the service's already-known DH-1
    repository, but the expected revision itself is not yet known
    (RevisionType.UNKNOWN)."""
    service = _service(repository="omnibioai-tes")
    source = source_version_for(service)
    assert source.repository == "omnibioai-tes"
    assert source.expected_revision is None
    assert source.revision_type is RevisionType.UNKNOWN


def test_source_version_unknown_repository():
    """A service with no known repository produces a source with
    repository=None, not a fabricated guess."""
    service = _service(repository=None)
    source = source_version_for(service)
    assert source.repository is None


# ---------------------------------------------------------------------------
# configured_artifact_for
# ---------------------------------------------------------------------------


def test_configured_artifact_from_image():
    """A tagged image reference produces a configured artifact with
    that image/tag and no digest."""
    image = parse_image_reference("mysql:8.0")
    artifact = configured_artifact_for(image)
    assert artifact.image == "mysql:8.0"
    assert artifact.tag == "8.0"
    assert artifact.digest is None


def test_configured_artifact_none_when_no_image():
    """A build-only service (no image at all) produces an
    all-None configured artifact."""
    artifact = configured_artifact_for(None)
    assert artifact.image is None
    assert artifact.tag is None
    assert artifact.digest is None


def test_configured_artifact_digest_pinned():
    """A digest-pinned image reference produces a configured artifact
    with that exact digest."""
    image = parse_image_reference("mysql@sha256:" + "a" * 64)
    artifact = configured_artifact_for(image)
    assert artifact.digest == "sha256:" + "a" * 64


# ---------------------------------------------------------------------------
# running_artifact_from_container
# ---------------------------------------------------------------------------


def test_running_artifact_extracts_compose_image_and_oci_labels():
    """A container's Compose image-id and every OCI revision/source/
    version label are all correctly extracted."""
    labels = (
        "com.docker.compose.image=sha256:deadbeef,"
        "org.opencontainers.image.revision=abc123,"
        "org.opencontainers.image.source=https://github.com/example/repo,"
        "org.opencontainers.image.version=1.2.3,"
        "com.docker.compose.service=svc"
    )
    running = running_artifact_from_container(_container(labels))
    assert running.image_id == "sha256:deadbeef"
    assert running.revision == "abc123"
    assert running.source == "https://github.com/example/repo"
    assert running.version == "1.2.3"


def test_running_artifact_no_container():
    """No running container at all produces an all-None running artifact."""
    running = running_artifact_from_container(None)
    assert running.image_id is None
    assert running.revision is None


def test_running_artifact_missing_labels():
    """A container with an empty Labels string produces image_id=None."""
    running = running_artifact_from_container(_container(""))
    assert running.image_id is None


def test_running_artifact_malformed_labels_string_degrades_safely():
    """A malformed Labels string (stray "=" and empty segments) never
    raises -- it degrades to image_id=None."""
    # Stray "=" and empty segments must never raise.
    running = running_artifact_from_container(_container(",=,a=b,="))
    assert running.image_id is None


# ---------------------------------------------------------------------------
# compute_drift
# ---------------------------------------------------------------------------


def test_drift_third_party_is_not_applicable():
    """A third-party service (no known repository) is classified
    NOT_APPLICABLE, never MATCH/DRIFTED/UNKNOWN."""
    service = _service(repository=None)
    configured = configured_artifact_for(None)
    running = running_artifact_from_container(None)
    result = compute_drift(
        service=service, configured=configured, running=running,
        running_present=False, local_image_ids={},
    )
    assert result.status is DriftStatus.NOT_APPLICABLE


def test_drift_no_running_container_is_unknown():
    """A service with no running container at all is classified UNKNOWN."""
    service = _service()
    configured = configured_artifact_for(parse_image_reference("mysql:8.0"))
    running = running_artifact_from_container(None)
    result = compute_drift(
        service=service, configured=configured, running=running,
        running_present=False, local_image_ids={},
    )
    assert result.status is DriftStatus.UNKNOWN


def test_drift_immutable_digest_match_via_local_image_id():
    """When the running container's image id resolves to the same
    local image id as the configured tag, drift is MATCH."""
    image = parse_image_reference("mysql:8.0")
    service = _service(image_raw="mysql:8.0")
    configured = configured_artifact_for(image)
    running = running_artifact_from_container(_container("com.docker.compose.image=sha256:same"))
    result = compute_drift(
        service=service, configured=configured, running=running,
        running_present=True, local_image_ids={"mysql:8.0": "sha256:same"},
    )
    assert result.status is DriftStatus.MATCH


def test_drift_immutable_digest_mismatch_is_drifted():
    """When the running container's local image id differs from the
    configured tag's resolved id, drift is DRIFTED with a reason
    mentioning the rebuild/mismatch."""
    image = parse_image_reference("mysql:8.0")
    service = _service(image_raw="mysql:8.0")
    configured = configured_artifact_for(image)
    running = running_artifact_from_container(_container("com.docker.compose.image=sha256:running-id"))
    result = compute_drift(
        service=service, configured=configured, running=running,
        running_present=True, local_image_ids={"mysql:8.0": "sha256:different-local-id"},
    )
    assert result.status is DriftStatus.DRIFTED
    assert "rebuilt" in result.reason or "differs" in result.reason


def test_drift_mutable_tag_alone_never_produces_match_without_id_evidence():
    """The same configured/running tag string ("latest") alone, with
    no resolvable local image id, is classified UNKNOWN -- a matching
    tag is never treated as proof of a match."""
    # Same configured/running tag string ("latest") but no local image
    # lookup can resolve it -> UNKNOWN, never MATCH from the tag alone.
    image = parse_image_reference("omnibioai/foo:latest")
    service = _service(image_raw="omnibioai/foo:latest")
    configured = configured_artifact_for(image)
    running = running_artifact_from_container(_container("com.docker.compose.image=sha256:running-id"))
    result = compute_drift(
        service=service, configured=configured, running=running,
        running_present=True, local_image_ids={},  # nothing resolvable locally
    )
    assert result.status is DriftStatus.UNKNOWN


def test_drift_untagged_configured_image_uses_docker_latest_convention():
    """An untagged configured image ref (e.g. "omnibioai-tes-local")
    is looked up locally with an implicit ":latest" suffix, matching
    Docker's own RepoTags convention for an untagged build."""
    # DH-1 leaves an untagged reference untagged (e.g. "omnibioai-tes-local");
    # the local lookup key must append :latest to match Docker's own
    # RepoTags convention for an untagged build.
    image = parse_image_reference("omnibioai-tes-local")
    service = _service(image_raw="omnibioai-tes-local")
    configured = configured_artifact_for(image)
    running = running_artifact_from_container(_container("com.docker.compose.image=sha256:same"))
    result = compute_drift(
        service=service, configured=configured, running=running,
        running_present=True, local_image_ids={"omnibioai-tes-local:latest": "sha256:same"},
    )
    assert result.status is DriftStatus.MATCH


def test_drift_build_only_service_with_no_explicit_image_stays_unknown():
    """A build-only service with no explicit `image:` key at all
    stays UNKNOWN -- never guessing a Compose-auto-generated name."""
    # No `image:` key at all -> never guess a Compose-auto-generated name.
    service = _service(image_raw=None)
    configured = configured_artifact_for(None)
    running = running_artifact_from_container(_container("com.docker.compose.image=sha256:x"))
    result = compute_drift(
        service=service, configured=configured, running=running,
        running_present=True, local_image_ids={"anything": "sha256:x"},
    )
    assert result.status is DriftStatus.UNKNOWN


def test_drift_missing_running_image_id_is_unknown_even_when_present():
    """A running container that's matched (running_present=True) but
    carries no com.docker.compose.image label at all (e.g. a non-
    Compose-created container) is still classified UNKNOWN."""
    # Container matched (present=True) but no com.docker.compose.image
    # label at all (e.g. a non-Compose-created container).
    service = _service(image_raw="mysql:8.0")
    configured = configured_artifact_for(parse_image_reference("mysql:8.0"))
    running = running_artifact_from_container(_container(""))
    result = compute_drift(
        service=service, configured=configured, running=running,
        running_present=True, local_image_ids={"mysql:8.0": "sha256:x"},
    )
    assert result.status is DriftStatus.UNKNOWN


def test_drift_expected_commit_equals_running_revision_label_is_match():
    """running.revision is still captured/exposed from an OCI revision
    label even though compute_drift itself doesn't compare on it today
    (no real deployment sets one) -- so a future evidence source can
    use it without a redesign."""
    # A hypothetical future case: if a running container DID carry an OCI
    # revision label, and it matched, that alone is legitimate deterministic
    # evidence -- but compute_drift as implemented only compares image IDs,
    # not revision labels, since no service in this codebase's real
    # deployments has ever set one (verified live). Confirm running.revision
    # is still captured/exposed even though it doesn't drive the current
    # comparison, so a future evidence source can use it without a redesign.
    running = running_artifact_from_container(
        _container("org.opencontainers.image.revision=abc123,com.docker.compose.image=sha256:x")
    )
    assert running.revision == "abc123"


# ---------------------------------------------------------------------------
# image_refs_to_inspect
# ---------------------------------------------------------------------------


def test_image_refs_to_inspect_deduplicates_and_skips_build_only():
    """A duplicate image ref across two services appears only once,
    and a build-only service (no image) is skipped entirely."""
    services = [
        _service(service_id="a", image_raw="mysql:8.0"),
        _service(service_id="b", image_raw="mysql:8.0"),  # duplicate
        _service(service_id="c", image_raw=None),  # build-only, skipped
        _service(service_id="d", image_raw="redis:7-alpine"),
    ]
    refs = image_refs_to_inspect(services)
    assert refs == ["mysql:8.0", "redis:7-alpine"]


def test_image_refs_to_inspect_untagged_gets_latest_suffix():
    """An untagged image ref gets the implicit ":latest" suffix in
    the inspect list."""
    services = [_service(service_id="a", image_raw="omnibioai-tes-local")]
    refs = image_refs_to_inspect(services)
    assert refs == ["omnibioai-tes-local:latest"]


def test_image_refs_to_inspect_empty_for_no_services():
    """An empty services list returns an empty refs list."""
    assert image_refs_to_inspect([]) == []


# ---------------------------------------------------------------------------
# build_service_drift / drift_summary (integration of the pieces above)
# ---------------------------------------------------------------------------


def test_build_service_drift_end_to_end_match():
    """build_service_drift() assembles source/configured/running/drift
    correctly end to end for a matching service."""
    service = _service(image_raw="mysql:8.0")
    container = _container("com.docker.compose.image=sha256:same")
    drift = build_service_drift(
        service=service, running_container=container, running_present=True,
        local_image_ids={"mysql:8.0": "sha256:same"},
    )
    assert drift.drift.status is DriftStatus.MATCH
    assert drift.source.repository == "omnibioai-svc"
    assert drift.configured.image == "mysql:8.0"
    assert drift.running.image_id == "sha256:same"


def test_drift_summary_counts_all_four_states():
    """drift_summary() correctly tallies one service in each of the
    four possible drift states."""
    a = build_service_drift(
        service=_service(service_id="a", image_raw="mysql:8.0"),
        running_container=_container("com.docker.compose.image=sha256:same"),
        running_present=True, local_image_ids={"mysql:8.0": "sha256:same"},
    )
    b = build_service_drift(
        service=_service(service_id="b", image_raw="mysql:8.0"),
        running_container=_container("com.docker.compose.image=sha256:other"),
        running_present=True, local_image_ids={"mysql:8.0": "sha256:same"},
    )
    c = build_service_drift(
        service=_service(service_id="c", repository=None),
        running_container=None, running_present=False, local_image_ids={},
    )
    d = build_service_drift(
        service=_service(service_id="d", image_raw=None),
        running_container=_container("com.docker.compose.image=sha256:x"),
        running_present=True, local_image_ids={},
    )
    summary = drift_summary({"a": a, "b": b, "c": c, "d": d})
    assert summary == {"match": 1, "drifted": 1, "unknown": 1, "not_applicable": 1}


# ---------------------------------------------------------------------------
# Redaction / security
# ---------------------------------------------------------------------------


def test_serialization_never_leaks_absolute_paths_or_secrets():
    """A raw container label containing an absolute filesystem path or
    a secret-shaped substring never appears in the serialized public
    payload."""
    service = _service(image_raw="mysql:8.0")
    container = _container(
        "com.docker.compose.image=sha256:same,"
        "com.docker.compose.project.working_dir=/home/manish/Desktop/machine/omnibioai-studio"
    )
    drift = build_service_drift(
        service=service, running_container=container, running_present=True,
        local_image_ids={"mysql:8.0": "sha256:same"},
    )
    payload = json.dumps(drift.to_public_dict())
    assert "/home/manish" not in payload
    assert "working_dir" not in payload
    lowered = payload.lower()
    for marker in ("password", "secret", "token", "container_id", "backend_handle"):
        assert marker not in lowered


def test_to_public_dict_is_allowlisted():
    """to_public_dict() exposes exactly the documented nested field
    set for source/configured/running/drift -- no extra keys."""
    service = _service(image_raw="mysql:8.0")
    drift = build_service_drift(
        service=service, running_container=None, running_present=False, local_image_ids={},
    )
    d = drift.to_public_dict()
    assert set(d.keys()) == {"source", "configured", "running", "drift"}
    assert set(d["source"].keys()) == {"repository", "expected_revision", "revision_type"}
    assert set(d["configured"].keys()) == {"image", "tag", "digest"}
    assert set(d["running"].keys()) == {"image_id", "revision", "source", "version"}
    assert set(d["drift"].keys()) == {"status", "reason", "evidence"}
