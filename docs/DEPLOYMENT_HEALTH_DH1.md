# Deployment Health -- DH-1: metadata and dependency model

DH-1 is the static, read-only foundation for the eventual Deployment Health
feature (`GET /deployment-health`, `platform.manage_infra`, V1 route
`/deployment-health` -- both still unbuilt). It derives a deterministic
service inventory and dependency topology from an explicitly supplied
Compose document. It is offline: no Docker, no network, no Prometheus, no
Regression Health, no live services. `control_center.deployment_health`
(`backend/src/control_center/deployment_health.py`) is the whole surface;
there is no HTTP endpoint or frontend yet -- that is DH-2 and DH-3.

## Compose is the deployment baseline

`load_compose_file`/`parse_compose_text` take an explicitly supplied path or
YAML text and an optional `baseline_source` (`development` / `release` /
`unknown`). DH-1 never guesses which Compose file is authoritative and never
merges multiple Compose files -- Studio's local and release stacks differ,
and resolving overlays correctly needs a reliable Compose-resolution
mechanism this repo doesn't have yet. That merge (if ever needed) is a
DH-2/DH-4 gap, not something DH-1 invents incomplete semantics for.

## Read-only, always

DH-1 models what Compose *declares*, not what is *running*. `depends_on` is
startup/topology evidence only -- it is never treated as proof that a
dependency is live or healthy. Propagating dependency edges into runtime
health status, and reusing the existing Docker inspection code instead of
duplicating it, are DH-2 work.

## Ownership semantics

Repository ownership is resolved in priority order, each tagged with the
evidence that produced it:

1. **Build context** (`COMPOSE_BUILD_CONTEXT`) -- an `omnibioai-<name>` path
   segment found in `build.context` or `build.dockerfile`. The strongest
   signal: it's literally where the image is built from.
2. **Image reference** (`COMPOSE_IMAGE`) -- an image published as
   `ghcr.io/omnibioai/omnibioai-<name>`.
3. **Static mapping** (`STATIC_OWNERSHIP_MAPPING`) -- a small curated table
   for services whose image/build metadata doesn't structurally encode the
   repo name (e.g. `toolserver` pulling a differently-shaped image).
4. A **relative build context** (`./something`, not `${VAR}`-prefixed, not
   absolute) is attributed to the caller-supplied `deployment_repository`
   (e.g. `"omnibioai-studio"`) -- it's built from inside that repo's own
   tree, not a sibling repo. This parameter is never hardcoded in the
   module; the caller supplies it.

Anything none of these can prove stays `repository=None`. DH-1 never invents
a human or team owner, and a curated table entry never overrides stronger
structural evidence when both exist.

## Category model

`ServiceCategory` is the fixed, extensible enum from the A1 discovery
(`CONTROL_PLANE`, `SECURITY`, `EXECUTION`, `SCIENTIFIC_DATA`, `AI_MODEL`,
`OBSERVABILITY`, `USER_INTERFACE`, `INFRASTRUCTURE`, `DATABASE_STORAGE`,
plus `UNKNOWN`). Categories come from a static `service_id -> category`
table captured from the discovery, the same shape as the ownership fallback
table. An unrecognized `service_id` resolves to `UNKNOWN`, never a guess
from name patterns.

## Dependency model

Every edge (`DeploymentDependency`) carries `from_service`, `to_service`, a
`DependencyRelationship`, and the `DeploymentEvidence` behind it. DH-1 only
ever derives `HARD` (from `depends_on` conditions `service_healthy` /
`service_completed_successfully`) and `SOFT` (`service_started`, or Compose
list-syntax with no condition) -- both are direct readings of what those
Compose conditions structurally mean, not an inference about application
behavior. `ROUTED_THROUGH` and `OBSERVABILITY_ONLY` exist in the enum for
DH-2+ (e.g. nginx routing, Prometheus scraping) but nothing in a Compose
file alone proves them yet, so DH-1 never assigns them. Two services
existing in the same Compose file is never treated as a dependency by
itself -- only an explicit `depends_on` entry is.

A `depends_on` target that isn't itself a defined service still produces an
edge (the declared topology, as written) with a `unknown_dependency_target`
warning on the inventory -- it doesn't fail the parse.

## Evidence model

`DeploymentEvidence(source, detail)` backs every fact DH-1 states, using
`EvidenceSource.{COMPOSE_SERVICE, COMPOSE_DEPENDS_ON, COMPOSE_IMAGE,
COMPOSE_BUILD_CONTEXT, STATIC_OWNERSHIP_MAPPING}`. `detail` is always a
safe, human-readable string -- never a raw path or environment value (see
Security below). The enum is intentionally not closed against future
sources: DH-2 adds `DOCKER_INSPECT`, `HTTP_PROBE`, `PROMETHEUS`, and
`REGRESSION_ARTIFACT` alongside these without redesigning the model.

## Image metadata

`parse_image_reference` splits a Compose `image:` string into registry,
repository, tag, and digest without resolving anything over the network.
`is_untagged` and `is_latest_tag` are both recorded explicitly -- `latest`
is a string tag like any other, never treated as a verified version.
Strings containing `${VAR}` references are parsed on a best-effort basis
(`has_variable=True`) rather than crashing; the variable reference text
itself is not a secret (it's already public in the checked-in Compose file)
and is safe to surface as-is.

## Metadata completeness

`MetadataCompleteness` covers only the three dimensions that can genuinely
be unknown: `repository_known`, `category_known`, `dependencies_known`
(false only when `depends_on` itself is unparseable). Tag/image presence
isn't modeled as a completeness gap -- a build-only service legitimately has
no `image:` key, and "no tag" is a fully known state, not a missing one.
`missing_fields` and `is_complete` are derived from those three booleans.

## Security / redaction

`to_public_dict()` on every model type is an explicit allowlist, never a
recursive dump of the underlying Compose structure. Concretely:

- Compose `environment:` blocks are never read by this module at all.
- Build context/dockerfile strings are scanned for an `omnibioai-<name>`
  path segment and then discarded -- only the matched, normalized
  repository name (or the generic "relative build context within
  `<repo>`" note) is ever recorded as evidence. The raw string, which may
  be an absolute host path, never appears in an evidence detail or a
  serialized field, even when it's what supplied the ownership evidence.
- `ports` extraction keeps only the container-side numeric port; a host
  bind IP/address is never recorded.
- There is no container ID, backend handle, Slurm ID, or credential field
  anywhere in the model -- there was never anywhere to source one from,
  since Docker/runtime state is out of scope for DH-1.

`backend/tests/test_deployment_health.py` asserts all of this directly
against the serialized JSON output, including a real absolute-path input
that does resolve ownership evidence (proving the resolved name is used
while the raw path is dropped), not just against inputs with nothing
sensitive to leak.

## Error semantics

`DeploymentHealthUnavailable(code)` is raised only for document-level
failures with no possible partial result: `compose_not_found`,
`invalid_yaml`, `root_not_mapping`, `invalid_services_key`. Everything else
in Compose's error space that section 15 of the DH-1 brief calls out --
missing `services:` key, empty `services:`, an invalid individual service
definition, a malformed `depends_on`, an unknown dependency target, an
unrecognized `service_id` for ownership/category -- degrades to
`UNKNOWN`/`None` on that one field, service, or edge, recorded in
`DeploymentInventory.warnings`, rather than failing the whole parse. DH-2
converts `DeploymentHealthUnavailable` into an HTTP response the same way
`regression_health.py`'s `RegressionHealthUnavailable` already is.

## Known gaps (DH-2 prerequisites)

- No HTTP endpoint and no wiring of a configured default Compose path yet
  (this module takes an explicit path always -- no `CONTROL_CENTER_*`-style
  env var default exists here on purpose).
- No live/runtime data: container state, health, restarts, resource usage
  are all DH-2 (reusing the existing Docker inspection code, not
  duplicating it) and DH-4.
- `ROUTED_THROUGH`/`OBSERVABILITY_ONLY` relationships are defined but never
  derived -- proving them needs application-level routing/scrape knowledge
  DH-1 doesn't have.
- Multi-file Compose overlay resolution (local `+dev-ports` style overlays,
  release vs. development) is not implemented; `baseline_source` records
  which single document was supplied, nothing more.
- No git revision, build timestamp, release version, image digest-as-proof-
  of-build, or architecture claims -- DH-1 only states what a field
  literally contains, never infers these.
