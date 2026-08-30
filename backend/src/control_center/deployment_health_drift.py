"""DH-5: source/commit/image drift visibility -- an additive extension of
Deployment Health, never a redesign. Every function here is pure and
takes already-fetched data; the only new I/O this milestone introduces is
one bounded, deduplicated `docker image inspect` batch call
(`routes_docker.get_local_image_ids`), reusing the exact same Docker
Socket Proxy access every other Deployment Health Docker call already
uses -- no second Docker client, no raw socket, no proxy allowlist
change (`GET /images/{name}/json` was already allowed, for this module's
own `/docker/plugin-images` local-image lookups).

## Evidence, deliberately conservative

Verified against the real, live ecosystem before this was designed, not
assumed: no current OmniBioAI-built image embeds an
`org.opencontainers.image.revision` (git-commit) label anywhere in this
deployment, so `SourceVersion.expected_revision` resolves to `UNKNOWN`
for every real service today -- an honest architecture finding this
module reports rather than papers over, not a bug to work around by
inferring a commit some other way (which section 5 of this milestone's
brief explicitly forbids: no timestamp/uptime/name-similarity guessing).

What *is* reliably available, with zero extra Docker calls: Compose's
own `com.docker.compose.image` container label -- the exact resolved
image ID Compose recorded when it created the container -- already
present in the same `docker ps` output DH-2 already fetches (parsed here
independently of DH-2's own `RuntimeState`, which stays byte-for-byte
unchanged -- see `_match_labels` below). Comparing that against a
bounded, deduplicated `docker image inspect` of each service's distinct
*known* configured image reference (never a guessed
Compose-auto-generated name for a build-only service with no explicit
`image:` key -- that stays `UNKNOWN`, never fabricated) is what actually
detects real drift here: a service that was rebuilt but not recreated.

## Why this survives the mutable-tag test

A configured `image:` reference is very often mutable (`:latest`, a
locally-built `-local` tag, or similar). Comparing raw tag strings would
be worthless. Every comparison here instead compares resolved,
*immutable* image IDs (sha256) on both sides -- the tag is only ever used
to *look up* which ID is currently tagged that way, never compared as a
string. `latest == latest` never produces `MATCH` by itself; the
underlying IDs must actually match (section 8's own carve-out: "unless
digest/image identity ... proves equality").
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from control_center.deployment_health import (
    DeploymentEvidence,
    DeploymentService,
    EvidenceSource,
    ImageReference,
)

_OCI_REVISION_LABEL = "org.opencontainers.image.revision"
_OCI_SOURCE_LABEL = "org.opencontainers.image.source"
_OCI_VERSION_LABEL = "org.opencontainers.image.version"
_COMPOSE_IMAGE_LABEL = "com.docker.compose.image"


class DriftStatus(str, Enum):
    MATCH = "match"
    DRIFTED = "drifted"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class RevisionType(str, Enum):
    """Where `SourceVersion.expected_revision` came from, if known --
    open for a future evidence source without redesigning this enum
    (mirrors how DH-1's own EvidenceSource is deliberately open-ended)."""

    OCI_LABEL = "oci_label"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SourceVersion:
    repository: str | None
    expected_revision: str | None
    revision_type: RevisionType

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "expected_revision": self.expected_revision,
            "revision_type": self.revision_type.value,
        }


@dataclass(frozen=True)
class ConfiguredArtifact:
    image: str | None
    tag: str | None
    digest: str | None

    def to_public_dict(self) -> dict[str, Any]:
        return {"image": self.image, "tag": self.tag, "digest": self.digest}


@dataclass(frozen=True)
class RunningArtifact:
    image_id: str | None
    revision: str | None
    source: str | None
    version: str | None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "image_id": self.image_id,
            "revision": self.revision,
            "source": self.source,
            "version": self.version,
        }


@dataclass(frozen=True)
class DriftResult:
    status: DriftStatus
    reason: str
    evidence: tuple[DeploymentEvidence, ...]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason": self.reason,
            "evidence": [e.to_public_dict() for e in self.evidence],
        }


@dataclass(frozen=True)
class ServiceDrift:
    source: SourceVersion
    configured: ConfiguredArtifact
    running: RunningArtifact
    drift: DriftResult

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.to_public_dict(),
            "configured": self.configured.to_public_dict(),
            "running": self.running.to_public_dict(),
            "drift": self.drift.to_public_dict(),
        }


# ---------------------------------------------------------------------------
# Label parsing (independent of DH-2's RuntimeState -- that dataclass and
# its to_public_dict() stay byte-for-byte unchanged; this reads the same
# already-fetched `docker ps` container dicts on its own)
# ---------------------------------------------------------------------------


def _parse_labels(raw_labels: str | None) -> dict[str, str]:
    if not raw_labels:
        return {}
    parsed: dict[str, str] = {}
    for pair in raw_labels.split(","):
        key, _, value = pair.partition("=")
        key = key.strip()
        if key:
            parsed[key] = value.strip()
    return parsed


def running_artifact_from_container(container: dict[str, Any] | None) -> RunningArtifact:
    """Extracts only the four safe, already-fetched label values this
    module cares about. `container` is the same per-service dict DH-2's
    own container matching already resolved -- never re-fetched, never a
    second Docker call."""
    if container is None:
        return RunningArtifact(None, None, None, None)
    labels = _parse_labels(container.get("Labels"))
    return RunningArtifact(
        image_id=labels.get(_COMPOSE_IMAGE_LABEL) or None,
        revision=labels.get(_OCI_REVISION_LABEL) or None,
        source=labels.get(_OCI_SOURCE_LABEL) or None,
        version=labels.get(_OCI_VERSION_LABEL) or None,
    )


# ---------------------------------------------------------------------------
# Source version
# ---------------------------------------------------------------------------


def source_version_for(service: DeploymentService) -> SourceVersion:
    """`repository` reuses DH-1's own ownership evidence verbatim --
    never re-derived. `expected_revision` is populated only from a
    concrete evidence source (currently: none exists anywhere in this
    codebase's real deployments -- see module docstring); it stays
    UNKNOWN rather than being guessed from a name, a timestamp, or
    anything else section 5 of this milestone's brief rules out."""
    return SourceVersion(
        repository=service.repository,
        expected_revision=None,
        revision_type=RevisionType.UNKNOWN,
    )


# ---------------------------------------------------------------------------
# Configured artifact
# ---------------------------------------------------------------------------


def configured_artifact_for(image: ImageReference | None) -> ConfiguredArtifact:
    if image is None:
        return ConfiguredArtifact(None, None, None)
    return ConfiguredArtifact(image=image.raw, tag=image.tag, digest=image.digest)


def _local_lookup_key(image: ImageReference) -> str:
    """The exact string `docker image inspect`'s own RepoTags would show
    for this reference -- Docker itself appends `:latest` to an untagged
    reference (confirmed against the real daemon), so the lookup key
    must too, or a genuine match would be silently missed."""
    if image.tag or image.digest or image.has_variable:
        return image.raw
    return f"{image.raw}:latest"


# ---------------------------------------------------------------------------
# Drift computation
# ---------------------------------------------------------------------------


def compute_drift(
    *,
    service: DeploymentService,
    configured: ConfiguredArtifact,
    running: RunningArtifact,
    running_present: bool,
    local_image_ids: dict[str, str],
) -> DriftResult:
    if service.repository is None:
        return DriftResult(
            DriftStatus.NOT_APPLICABLE,
            "no OmniBioAI repository ownership evidence for this service -- "
            "likely third-party infrastructure with nothing to compare against",
            (),
        )

    if not running_present or not running.image_id:
        return DriftResult(
            DriftStatus.UNKNOWN,
            "no running container / resolved image identity evidence available",
            (),
        )

    if service.image is not None:
        lookup_key = _local_lookup_key(service.image)
        local_id = local_image_ids.get(lookup_key)
        if local_id is not None:
            evidence = (
                DeploymentEvidence(
                    EvidenceSource.DOCKER_INSPECT,
                    f"running image id compared against the currently locally-tagged "
                    f"image for '{lookup_key}'",
                ),
            )
            if local_id == running.image_id:
                return DriftResult(
                    DriftStatus.MATCH,
                    "running container's image id matches the currently "
                    "locally-tagged image for its configured reference",
                    evidence,
                )
            return DriftResult(
                DriftStatus.DRIFTED,
                "running container's image id differs from the currently "
                "locally-tagged image for its configured reference -- "
                "likely rebuilt without being recreated",
                evidence,
            )

    return DriftResult(
        DriftStatus.UNKNOWN,
        "insufficient evidence to compare the configured and running artifacts",
        (),
    )


def build_service_drift(
    *,
    service: DeploymentService,
    running_container: dict[str, Any] | None,
    running_present: bool,
    local_image_ids: dict[str, str],
) -> ServiceDrift:
    source = source_version_for(service)
    configured = configured_artifact_for(service.image)
    running = running_artifact_from_container(running_container)
    drift = compute_drift(
        service=service, configured=configured, running=running,
        running_present=running_present, local_image_ids=local_image_ids,
    )
    return ServiceDrift(source=source, configured=configured, running=running, drift=drift)


def image_refs_to_inspect(services: list[DeploymentService]) -> list[str]:
    """The distinct, *known* configured image references worth a local
    `docker image inspect` call -- deduplicated, and only for services
    where DH-1 actually found an explicit `image:` key (never a guessed
    Compose-auto-generated name for a build-only service)."""
    refs: set[str] = set()
    for service in services:
        if service.image is not None:
            refs.add(_local_lookup_key(service.image))
    return sorted(refs)


def drift_summary(drifts: dict[str, ServiceDrift]) -> dict[str, int]:
    counts = {status.value: 0 for status in DriftStatus}
    for service_drift in drifts.values():
        counts[service_drift.drift.status.value] += 1
    return counts
