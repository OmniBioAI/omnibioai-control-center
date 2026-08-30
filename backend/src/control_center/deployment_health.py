"""DH-1: static, read-only deployment metadata and dependency model.

This module derives a deterministic inventory of Compose-defined services --
ownership, category, dependency topology, image metadata, and evidence for
each fact -- from an explicitly supplied Compose document. It never touches
Docker, the network, Prometheus, or Regression Health, and it never reads or
returns `.env`/environment values.

Scope boundary (see the DH-1 architecture doc for the full explanation):
  * Compose `depends_on` is modeled as deployment/startup topology only. It
    is not runtime health, and DH-1 does not claim otherwise. Propagating
    dependency edges into live health status is DH-2.
  * Only `HARD` and `SOFT` relationships are ever derived here, from
    `depends_on` condition semantics (`service_healthy` /
    `service_completed_successfully` => HARD, `service_started` or no
    condition => SOFT). `ROUTED_THROUGH` and `OBSERVABILITY_ONLY` exist in
    the enum for forward compatibility but nothing in DH-1 can prove them
    from static Compose metadata alone -- inferring them requires
    application-level routing/scrape knowledge that belongs to a later
    milestone.
  * Missing metadata (unknown ownership, unknown category, an unparseable
    `depends_on`) is represented as UNKNOWN/None, never inferred or
    fabricated.

Redaction: only an explicit allowlist of fields ever reaches
`to_public_dict()`. Build context/dockerfile path strings are matched for a
repository name and then discarded -- the raw string (which may be an
absolute host path) is never included in any evidence detail or serialized
field. Environment values are never read from Compose service definitions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class DeploymentHealthUnavailable(ValueError):
    """Raised when a Compose document cannot safely be modeled at all.

    Reserved for document-level failures where no partial result is
    possible (missing file, invalid YAML, a root that isn't a mapping, or a
    `services` key that isn't a mapping). Per-service anomalies (a
    malformed `depends_on`, an unrecognized service definition, an unknown
    dependency target) do not raise -- they degrade to UNKNOWN/None on that
    one service or edge and are recorded in `DeploymentInventory.warnings`,
    so one bad entry never blocks modeling the rest of the deployment.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ServiceCategory(str, Enum):
    CONTROL_PLANE = "control_plane"
    SECURITY = "security"
    EXECUTION = "execution"
    SCIENTIFIC_DATA = "scientific_data"
    AI_MODEL = "ai_model"
    OBSERVABILITY = "observability"
    USER_INTERFACE = "user_interface"
    INFRASTRUCTURE = "infrastructure"
    DATABASE_STORAGE = "database_storage"
    UNKNOWN = "unknown"


class DependencyRelationship(str, Enum):
    HARD = "hard"
    SOFT = "soft"
    ROUTED_THROUGH = "routed_through"
    OBSERVABILITY_ONLY = "observability_only"


class EvidenceSource(str, Enum):
    COMPOSE_SERVICE = "compose_service"
    COMPOSE_DEPENDS_ON = "compose_depends_on"
    COMPOSE_IMAGE = "compose_image"
    COMPOSE_BUILD_CONTEXT = "compose_build_context"
    STATIC_OWNERSHIP_MAPPING = "static_ownership_mapping"
    # DH-2: runtime evidence sources, added here per this module's own
    # "without redesigning the core model" promise -- nothing else in DH-1
    # changes. DH-1 itself never produces these; only DH-2's runtime-merge
    # layer (control_center.deployment_health_runtime) does.
    DOCKER_INSPECT = "docker_inspect"
    HTTP_PROBE = "http_probe"
    PROMETHEUS = "prometheus"
    REGRESSION_ARTIFACT = "regression_artifact"


class BaselineSource(str, Enum):
    """Which Compose baseline the caller asserts this document is.

    DH-1 never guesses this and never merges multiple Compose files -- the
    caller supplies it explicitly (see module docstring and the
    architecture doc's "local vs release Compose" section).
    """

    DEVELOPMENT = "development"
    RELEASE = "release"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DeploymentEvidence:
    """One fact and the safe, non-path/non-secret detail backing it."""

    source: EvidenceSource
    detail: str

    def to_public_dict(self) -> dict[str, Any]:
        return {"source": self.source.value, "detail": self.detail}


@dataclass(frozen=True)
class ImageReference:
    repository: str | None
    tag: str | None
    digest: str | None
    registry: str | None
    has_variable: bool
    is_untagged: bool
    is_latest_tag: bool
    raw: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "registry": self.registry,
            "repository": self.repository,
            "tag": self.tag,
            "digest": self.digest,
            "has_variable": self.has_variable,
            "is_untagged": self.is_untagged,
            "is_latest_tag": self.is_latest_tag,
        }


@dataclass(frozen=True)
class MetadataCompleteness:
    """Only the dimensions that can genuinely be UNKNOWN.

    Tag/image presence is not modeled here: a build-only service
    legitimately has no `image:` key, and an untagged image is a fully
    known state (we know there is no tag), not a gap. Repository
    (ownership), category, and dependency-parseability are the three facts
    that can actually be missing/unproven, so those are what "completeness"
    means for DH-1.
    """

    repository_known: bool
    category_known: bool
    dependencies_known: bool

    @property
    def missing_fields(self) -> tuple[str, ...]:
        missing = []
        if not self.repository_known:
            missing.append("repository")
        if not self.category_known:
            missing.append("category")
        if not self.dependencies_known:
            missing.append("dependencies")
        return tuple(missing)

    @property
    def is_complete(self) -> bool:
        return not self.missing_fields

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "repository_known": self.repository_known,
            "category_known": self.category_known,
            "dependencies_known": self.dependencies_known,
            "missing_fields": list(self.missing_fields),
            "is_complete": self.is_complete,
        }


@dataclass(frozen=True)
class DeploymentService:
    service_id: str
    display_name: str
    category: ServiceCategory
    repository: str | None
    ownership_evidence: DeploymentEvidence | None
    image: ImageReference | None
    build_configured: bool
    healthcheck_configured: bool
    ports: tuple[int, ...]
    dependency_count: int
    evidence: tuple[DeploymentEvidence, ...]
    completeness: MetadataCompleteness

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "service_id": self.service_id,
            "display_name": self.display_name,
            "category": self.category.value,
            "repository": self.repository,
            "ownership_evidence": (
                self.ownership_evidence.to_public_dict() if self.ownership_evidence else None
            ),
            "image": self.image.to_public_dict() if self.image else None,
            "build_configured": self.build_configured,
            "healthcheck_configured": self.healthcheck_configured,
            "ports": list(self.ports),
            "dependency_count": self.dependency_count,
            "evidence": [item.to_public_dict() for item in self.evidence],
            "completeness": self.completeness.to_public_dict(),
        }


@dataclass(frozen=True)
class DeploymentDependency:
    from_service: str
    to_service: str
    relationship: DependencyRelationship
    evidence: DeploymentEvidence

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "from_service": self.from_service,
            "to_service": self.to_service,
            "relationship": self.relationship.value,
            "evidence": self.evidence.to_public_dict(),
        }


@dataclass(frozen=True)
class DeploymentInventory:
    baseline_source: BaselineSource
    services: tuple[DeploymentService, ...]
    dependencies: tuple[DeploymentDependency, ...]
    warnings: tuple[str, ...]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "baseline_source": self.baseline_source.value,
            "services": [service.to_public_dict() for service in self.services],
            "dependencies": [dep.to_public_dict() for dep in self.dependencies],
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# Ownership mapping
# ---------------------------------------------------------------------------

# Section 5's examples verbatim. This is the fallback tier -- structural
# evidence (build context, then published image path) is preferred and
# checked first in _resolve_ownership. This table only decides ownership
# for services where neither structural signal is present (pure-image
# services with a non-omnibioai-shaped image reference).
_STATIC_OWNERSHIP: dict[str, str] = {
    "auth-service": "omnibioai-auth",
    "api-gateway": "omnibioai-api-gateway",
    "policy-engine": "omnibioai-policy-engine",
    "hpc-policy-engine": "omnibioai-hpc-policy-engine",
    "security-audit": "omnibioai-security-audit",
    "tes": "omnibioai-tes",
    "toolserver": "omnibioai-toolserver",
    "model-registry": "omnibioai-model-registry",
    "lims": "omnibioai-lims",
    "rag": "omnibioai-rag",
    "workbench": "omnibioai-workbench",
    "workflow-bundles": "omnibioai-workflow-bundles",
    "tool-images": "omnibioai-tool-images",
    "control-center": "omnibioai-control-center",
    "control-center-web": "omnibioai-control-center",
    "billing-service": "omnibioai-billing",
    "billing-worker": "omnibioai-billing",
}

# Known Studio service_id -> category, captured from the A1 discovery.
# service_ids that never appear here resolve to ServiceCategory.UNKNOWN --
# deliberately not guessed from name patterns, per "missing metadata must
# remain UNKNOWN rather than being inferred."
_STATIC_CATEGORY: dict[str, ServiceCategory] = {
    "mysql": ServiceCategory.DATABASE_STORAGE,
    "redis": ServiceCategory.DATABASE_STORAGE,
    "neo4j": ServiceCategory.DATABASE_STORAGE,
    "deploy-verify": ServiceCategory.INFRASTRUCTURE,
    "nginx-router": ServiceCategory.INFRASTRUCTURE,
    "docker-socket-proxy": ServiceCategory.SECURITY,
    "toolserver": ServiceCategory.EXECUTION,
    "tes": ServiceCategory.EXECUTION,
    "workbench": ServiceCategory.EXECUTION,
    "celery-worker": ServiceCategory.EXECUTION,
    "model-registry": ServiceCategory.AI_MODEL,
    "ollama": ServiceCategory.AI_MODEL,
    "rag": ServiceCategory.AI_MODEL,
    "billing-service": ServiceCategory.CONTROL_PLANE,
    "billing-worker": ServiceCategory.CONTROL_PLANE,
    "control-center": ServiceCategory.CONTROL_PLANE,
    "control-center-web": ServiceCategory.CONTROL_PLANE,
    "api-gateway": ServiceCategory.CONTROL_PLANE,
    "license-server": ServiceCategory.CONTROL_PLANE,
    "lims": ServiceCategory.SCIENTIFIC_DATA,
    "workflow-bundles": ServiceCategory.SCIENTIFIC_DATA,
    "tool-images": ServiceCategory.SCIENTIFIC_DATA,
    "dev-hub": ServiceCategory.USER_INTERFACE,
    "launcher": ServiceCategory.USER_INTERFACE,
    "jupyter": ServiceCategory.USER_INTERFACE,
    "rstudio": ServiceCategory.USER_INTERFACE,
    "vscode": ServiceCategory.USER_INTERFACE,
    "videos": ServiceCategory.USER_INTERFACE,
    "web-ui": ServiceCategory.USER_INTERFACE,
    "opa": ServiceCategory.SECURITY,
    "auth-service": ServiceCategory.SECURITY,
    "interaction-worker": ServiceCategory.SECURITY,
    "policy-engine": ServiceCategory.SECURITY,
    "hpc-policy-engine": ServiceCategory.SECURITY,
    "security-audit": ServiceCategory.SECURITY,
    "security-audit-worker": ServiceCategory.SECURITY,
    "prometheus": ServiceCategory.OBSERVABILITY,
    "grafana": ServiceCategory.OBSERVABILITY,
    "cadvisor": ServiceCategory.OBSERVABILITY,
    "redis-exporter": ServiceCategory.OBSERVABILITY,
    "node-exporter": ServiceCategory.OBSERVABILITY,
}

_ACRONYMS = {
    "tes": "TES", "hpc": "HPC", "lims": "LIMS", "rag": "RAG", "opa": "OPA",
    "api": "API", "ui": "UI", "vscode": "VSCode",
}

_REPO_SEGMENT_RE = re.compile(r"^omnibioai-[a-z0-9][a-z0-9-]*$", re.IGNORECASE)
_GHCR_IMAGE_RE = re.compile(
    r"^ghcr\.io/omnibioai/(omnibioai-[a-z0-9][a-z0-9-]*)(?::|@|$)", re.IGNORECASE
)
_DIGEST_RE = re.compile(r"^(?P<name>.+)@(?P<digest>[a-zA-Z0-9_+.-]+:[0-9a-fA-F]+)$")


def _display_name(service_id: str) -> str:
    return " ".join(_ACRONYMS.get(word.lower(), word.capitalize()) for word in service_id.split("-"))


def _repo_from_path_segments(*values: str | None) -> str | None:
    """First `omnibioai-<name>` path segment across the given strings, in
    order. Only the matched segment is ever returned -- the input strings
    themselves (which may be absolute host paths) are discarded."""
    for value in values:
        if not value:
            continue
        for segment in value.split("/"):
            if _REPO_SEGMENT_RE.match(segment):
                return segment.lower()
    return None


def _repo_from_image(raw_image: str | None) -> str | None:
    if not raw_image:
        return None
    match = _GHCR_IMAGE_RE.match(raw_image)
    return match.group(1).lower() if match else None


def _is_relative_local_path(value: str) -> bool:
    stripped = value.strip()
    return bool(stripped) and not stripped.startswith("${") and not stripped.startswith("/")


def _resolve_ownership(
    service_id: str,
    build_context: str | None,
    build_dockerfile: str | None,
    image_raw: str | None,
    *,
    deployment_repository: str | None,
) -> tuple[str | None, DeploymentEvidence | None]:
    repo = _repo_from_path_segments(build_context, build_dockerfile)
    if repo:
        return repo, DeploymentEvidence(
            EvidenceSource.COMPOSE_BUILD_CONTEXT, f"build context path segment matched '{repo}'"
        )

    repo = _repo_from_image(image_raw)
    if repo:
        return repo, DeploymentEvidence(
            EvidenceSource.COMPOSE_IMAGE, f"image published under '{repo}'"
        )

    static_repo = _STATIC_OWNERSHIP.get(service_id)
    if static_repo:
        return static_repo, DeploymentEvidence(
            EvidenceSource.STATIC_OWNERSHIP_MAPPING, f"known mapping for service '{service_id}'"
        )

    if build_context and deployment_repository and _is_relative_local_path(build_context):
        return deployment_repository, DeploymentEvidence(
            EvidenceSource.COMPOSE_BUILD_CONTEXT,
            f"relative build context within '{deployment_repository}'",
        )

    return None, None


# ---------------------------------------------------------------------------
# Image reference parsing
# ---------------------------------------------------------------------------


def parse_image_reference(raw: str) -> ImageReference:
    """Parse a Compose `image:` string without resolving anything over the
    network. Handles registry/repository/tag, digest references, untagged
    images, and images containing unresolved `${VAR}` references."""
    has_variable = "${" in raw

    working = raw
    digest: str | None = None
    digest_match = _DIGEST_RE.match(raw)
    if digest_match:
        working = digest_match.group("name")
        digest = digest_match.group("digest")

    segments = working.split("/")
    last = segments[-1]
    tag: str | None = None
    if ":" in last:
        name_part, _, tag = last.rpartition(":")
        segments = [*segments[:-1], name_part]
    working_no_tag = "/".join(segments)

    parts = working_no_tag.split("/")
    registry: str | None = None
    repository = working_no_tag or None
    if len(parts) > 1 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        registry = parts[0]
        repository = "/".join(parts[1:]) or None

    return ImageReference(
        raw=raw,
        registry=registry,
        repository=repository,
        tag=tag,
        digest=digest,
        has_variable=has_variable,
        is_untagged=tag is None and digest is None,
        is_latest_tag=tag == "latest",
    )


def _extract_container_port(entry: Any) -> int | None:
    """Only the container-side port number is ever extracted -- never a
    host bind IP/address, which could disclose network topology."""
    if isinstance(entry, bool):
        return None
    if isinstance(entry, int):
        return entry
    if isinstance(entry, dict):
        target = entry.get("target")
        return target if isinstance(target, int) and not isinstance(target, bool) else None
    if isinstance(entry, str):
        spec = entry.split("/")[0]
        last = spec.split(":")[-1]
        try:
            return int(last)
        except ValueError:
            return None
    return None


def _extract_ports(raw_ports: Any) -> tuple[int, ...]:
    if not isinstance(raw_ports, list):
        return ()
    ports = {p for entry in raw_ports if (p := _extract_container_port(entry)) is not None}
    return tuple(sorted(ports))


# ---------------------------------------------------------------------------
# Dependency parsing
# ---------------------------------------------------------------------------

_HARD_CONDITIONS = {"service_healthy", "service_completed_successfully"}


def _relationship_from_condition(condition: str | None) -> DependencyRelationship:
    return DependencyRelationship.HARD if condition in _HARD_CONDITIONS else DependencyRelationship.SOFT


def _make_dependency(
    from_service: str, to_service: str, condition: str | None, known_ids: set[str], warnings: list[str]
) -> DeploymentDependency:
    if to_service not in known_ids:
        warnings.append(f"unknown_dependency_target:{from_service}->{to_service}")
    detail = f"depends_on '{to_service}'"
    if condition:
        detail += f" (condition={condition})"
    return DeploymentDependency(
        from_service=from_service,
        to_service=to_service,
        relationship=_relationship_from_condition(condition),
        evidence=DeploymentEvidence(EvidenceSource.COMPOSE_DEPENDS_ON, detail),
    )


def _parse_depends_on(
    service_id: str, raw_depends_on: Any, known_ids: set[str]
) -> tuple[list[DeploymentDependency], bool, list[str]]:
    """Returns (dependencies, dependencies_known, warnings)."""
    warnings: list[str] = []
    if raw_depends_on is None:
        return [], True, warnings

    deps: list[DeploymentDependency] = []
    if isinstance(raw_depends_on, list):
        for target in raw_depends_on:
            if not isinstance(target, str):
                warnings.append(f"malformed_depends_on:{service_id}")
                continue
            deps.append(_make_dependency(service_id, target, None, known_ids, warnings))
    elif isinstance(raw_depends_on, dict):
        for target, cfg in raw_depends_on.items():
            condition = None
            if isinstance(cfg, dict):
                condition = cfg.get("condition")
            elif cfg is not None:
                warnings.append(f"malformed_depends_on:{service_id}")
            deps.append(_make_dependency(service_id, target, condition, known_ids, warnings))
    else:
        warnings.append(f"malformed_depends_on:{service_id}")
        return [], False, warnings

    return deps, True, warnings


# ---------------------------------------------------------------------------
# Service / document parsing
# ---------------------------------------------------------------------------


def _parse_service(
    service_id: str, cfg: dict[str, Any], *, deployment_repository: str | None, known_ids: set[str]
) -> tuple[DeploymentService, list[DeploymentDependency], list[str]]:
    warnings: list[str] = []

    build_cfg = cfg.get("build")
    build_configured = build_cfg is not None
    build_context: str | None = None
    build_dockerfile: str | None = None
    if isinstance(build_cfg, dict):
        context = build_cfg.get("context")
        dockerfile = build_cfg.get("dockerfile")
        build_context = context if isinstance(context, str) else None
        build_dockerfile = dockerfile if isinstance(dockerfile, str) else None
    elif isinstance(build_cfg, str):
        build_context = build_cfg

    image_raw = cfg.get("image")
    image_raw = image_raw if isinstance(image_raw, str) else None
    image_ref = parse_image_reference(image_raw) if image_raw else None

    repository, ownership_evidence = _resolve_ownership(
        service_id, build_context, build_dockerfile, image_raw,
        deployment_repository=deployment_repository,
    )

    category = _STATIC_CATEGORY.get(service_id, ServiceCategory.UNKNOWN)
    healthcheck_configured = isinstance(cfg.get("healthcheck"), dict)
    ports = _extract_ports(cfg.get("ports"))

    deps, dependencies_known, dep_warnings = _parse_depends_on(
        service_id, cfg.get("depends_on"), known_ids
    )
    warnings.extend(dep_warnings)

    evidence = [DeploymentEvidence(EvidenceSource.COMPOSE_SERVICE, f"service '{service_id}' defined in compose")]
    if ownership_evidence:
        evidence.append(ownership_evidence)
    if image_raw:
        evidence.append(DeploymentEvidence(EvidenceSource.COMPOSE_IMAGE, f"image '{image_raw}'"))
    evidence.extend(dep.evidence for dep in deps)

    service = DeploymentService(
        service_id=service_id,
        display_name=_display_name(service_id),
        category=category,
        repository=repository,
        ownership_evidence=ownership_evidence,
        image=image_ref,
        build_configured=build_configured,
        healthcheck_configured=healthcheck_configured,
        ports=ports,
        dependency_count=len(deps),
        evidence=tuple(evidence),
        completeness=MetadataCompleteness(
            repository_known=repository is not None,
            category_known=category is not ServiceCategory.UNKNOWN,
            dependencies_known=dependencies_known,
        ),
    )
    return service, deps, warnings


def _build_inventory(
    document: Any, *, baseline_source: BaselineSource, deployment_repository: str | None
) -> DeploymentInventory:
    if document is None:
        return DeploymentInventory(
            baseline_source=baseline_source, services=(), dependencies=(), warnings=("empty_document",)
        )
    if not isinstance(document, dict):
        raise DeploymentHealthUnavailable("root_not_mapping")

    raw_services = document.get("services")
    if raw_services is None:
        return DeploymentInventory(
            baseline_source=baseline_source, services=(), dependencies=(), warnings=("missing_services_key",)
        )
    if not isinstance(raw_services, dict):
        raise DeploymentHealthUnavailable("invalid_services_key")

    warnings: list[str] = []
    if not raw_services:
        warnings.append("empty_services")

    known_ids = set(raw_services.keys())
    services: list[DeploymentService] = []
    dependencies: list[DeploymentDependency] = []

    for service_id, raw_cfg in raw_services.items():
        if not isinstance(raw_cfg, dict):
            warnings.append(f"invalid_service_definition:{service_id}")
            continue
        service, service_deps, service_warnings = _parse_service(
            service_id, raw_cfg, deployment_repository=deployment_repository, known_ids=known_ids,
        )
        services.append(service)
        dependencies.extend(service_deps)
        warnings.extend(service_warnings)

    return DeploymentInventory(
        baseline_source=baseline_source,
        services=tuple(services),
        dependencies=tuple(dependencies),
        warnings=tuple(warnings),
    )


def parse_compose_text(
    text: str,
    *,
    baseline_source: BaselineSource = BaselineSource.UNKNOWN,
    deployment_repository: str | None = None,
) -> DeploymentInventory:
    """Parse already-loaded Compose YAML text into a DeploymentInventory.

    `deployment_repository` is an optional logical repo name (e.g.
    "omnibioai-studio"), supplied by the caller -- never hardcoded here --
    used only to attribute ownership for services whose build context is a
    genuinely relative local path (not `${VAR}`-prefixed, not absolute),
    i.e. built from within the Compose file's own repository rather than a
    sibling `omnibioai-*` repo.
    """
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError:
        raise DeploymentHealthUnavailable("invalid_yaml") from None
    return _build_inventory(
        document, baseline_source=baseline_source, deployment_repository=deployment_repository
    )


def load_compose_file(
    path: str | Path,
    *,
    baseline_source: BaselineSource = BaselineSource.UNKNOWN,
    deployment_repository: str | None = None,
) -> DeploymentInventory:
    """Load and parse an explicitly supplied Compose file path. The path is
    always caller-supplied -- this function has no default/developer-
    specific path of its own; wiring a configured default belongs to DH-2's
    HTTP layer, not this model."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        raise DeploymentHealthUnavailable("compose_not_found") from None
    return parse_compose_text(
        text, baseline_source=baseline_source, deployment_repository=deployment_repository
    )
