# Deployment Health -- DH-2: backend integration

DH-2 exposes `GET /deployment-health`, merging DH-1's static Compose model
(`docs/DEPLOYMENT_HEALTH_DH1.md`) with existing runtime/probe/monitoring
sources. It reuses those sources rather than reimplementing them; the
logic-heavy merge/health computation lives in
`control_center.deployment_health_runtime` as pure functions, and
`api/routes_deployment_health.py` does the actual I/O.

## Endpoint and authorization

`GET /deployment-health`, gated by the existing `platform.manage_infra`
permission -- the same one `regression_health_router`/`docker_router`/
`services_router`/`summary_router` already use in `main.py` for identical
"leaks real topology/identity data" reasoning. Standard semantics:
unauthenticated -> 401, authenticated without the permission -> 403,
authorized -> 200. Read-only: `GET` only, no mutating verbs, no restart/
stop/deploy/control action anywhere in this milestone.

## Configuration

Three environment variables, none with a developer-specific default:

- `DEPLOYMENT_HEALTH_COMPOSE_PATH` -- the Compose file to load. Unset ->
  the endpoint returns the safe 503 below; DH-4 is responsible for wiring
  the real deployed path.
- `DEPLOYMENT_HEALTH_BASELINE_SOURCE` -- `development` / `release` /
  `unknown` (default). An unrecognized value also falls back to `unknown`
  rather than erroring.
- `DEPLOYMENT_HEALTH_DEPLOYMENT_REPOSITORY` -- optional; the logical repo
  name DH-1 attributes a relative build context to (e.g.
  `"omnibioai-studio"`). Unset -> those specific services (Studio's own
  `web-ui`/`license-server`/`docker-socket-proxy`) just stay `UNKNOWN`
  ownership, not a functional break.

None of these are ever echoed back in the response body.

## Response shape

```
{
  generated_at, baseline,
  summary: { total, healthy, degraded, unhealthy, unknown },
  services: [ { service_id, display_name, category, repository,
                deployment: { image, build_configured, healthcheck_configured, ports },
                runtime: { present, running, docker_health, image, match_evidence },
                health: { intrinsic, intrinsic_evidence, effective, effective_evidence },
                image_comparison: { status, configured, running },
                dependencies: [ { to_service, relationship, target_intrinsic_health } ],
                evidence, completeness } ],
  regression_health: { availability, phases, freshness },
  data_sources: { compose, docker, application_probe, prometheus, regression_health },
  warnings: [...]
}
```

`summary.total` and every count come from `len(inventory.services)` at
request time -- nothing is hardcoded to today's 41. If Compose grows to 42
services, the endpoint reports 42 without a code change.

## Intrinsic vs. effective health

Every service carries two health values, both from
`{HEALTHY, DEGRADED, UNHEALTHY, UNKNOWN}`:

- **Intrinsic**: the service's own evidence, independent of dependencies.
  Precedence (verified against this repo's real architecture, not
  assumed): `core.runner.run_all_checks` (the same application-probe layer
  `GET /services`/`GET /summary` already expose, keyed by the same
  service_id as Compose) beats Docker's healthcheck state, which beats
  bare "container is running" (evidence of nothing about service health),
  which beats `UNKNOWN`. A running container with no healthcheck and no
  probe configured for it is `UNKNOWN`, never `HEALTHY` --
  **CONTAINER RUNNING != SERVICE HEALTHY** is enforced structurally, not
  by convention.
- **Effective**: intrinsic health adjusted for `HARD` dependency evidence
  only. `SOFT` dependency failures are recorded as informational evidence
  and never change it. `UNHEALTHY` is reserved exclusively for intrinsic
  failure -- a dependency problem can push a service to `DEGRADED` at
  most, generalizing the brief's own TES/ToolServer example into an
  explicit, always-true invariant.

## Dependency propagation is exactly one hop

Effective health for service A consults only A's own intrinsic health and
the **intrinsic** (never effective) health of A's direct dependencies. It
never walks a dependency's own dependencies. This is what makes the
computation cycle-safe and `O(services + edges)` by construction -- with
no multi-hop traversal, a dependency cycle cannot cause recursion or a
status explosion, because there is no recursion to begin with. Verified
with a direct A<->B cycle test in
`test_deployment_health_runtime.py::test_effective_health_dependency_cycle_does_not_hang_or_recurse`.

Propagation table (`deployment_health_runtime.effective_health`):

1. intrinsic `UNHEALTHY` -> effective `UNHEALTHY` (dependencies irrelevant)
2. intrinsic `UNKNOWN`, no HARD dependency `UNHEALTHY` -> `UNKNOWN`
3. intrinsic `UNKNOWN`, some HARD dependency `UNHEALTHY` -> `DEGRADED`
   (a confirmed-unhealthy hard dependency is stronger evidence than no
   evidence at all)
4. intrinsic `HEALTHY`/`DEGRADED`, some HARD dependency `UNHEALTHY` ->
   `DEGRADED`
5. intrinsic `HEALTHY`/`DEGRADED`, no HARD dep `UNHEALTHY` but some HARD
   dep `UNKNOWN` -> `DEGRADED` (an unproven hard dependency is a caution
   signal, not silently reported as fully healthy)
6. intrinsic `HEALTHY`/`DEGRADED`, all HARD deps `HEALTHY`/`DEGRADED` (or
   no HARD deps at all) -> effective = intrinsic

## Data source availability

`data_sources` never turns an optional source's outage into a fatal
response -- only Compose/DH-1 failing does that (see Failure semantics
below). Each source:

- `compose`: always `available` if the response was produced at all.
- `docker`: `available`/`unavailable`, from
  `routes_docker.get_containers_status()` (reused verbatim -- see Docker
  reuse below). Unavailable -> every service's runtime state is `UNKNOWN`,
  never fabricated as healthy.
- `application_probe`: `available`/`unavailable`, from
  `core.settings.load_settings()` + `core.runner.run_all_checks()` (also
  reused verbatim). A service absent from `config/control_center.yaml`
  simply has no probe evidence for it; that's a per-service gap, not this
  flag.
- `prometheus`: `available`/`unavailable`/`not_configured`, from the
  existing `analytics.prometheus` client (see Prometheus below).
- `regression_health`: `available`/`unavailable`, from
  `regression_health.load_regression_health()` (reused verbatim; see
  Regression Health below). This source has no "not configured" state --
  unlike `PROMETHEUS_URL`, the artifact path always resolves to *some*
  location, so any failure to load it is `unavailable`.

## Docker reuse

`routes_docker.get_containers_status()` -- the exact function
`routes_dashboard.py`'s aggregator already reuses -- is called as-is; DH-2
adds no second Docker-inspection implementation. It never raises: an
`"error"` key in its result is treated as Docker being entirely
unavailable (`containers=None` downstream), not a crash.

**Service matching** (`deployment_health_runtime.match_containers_to_services`):
the Compose label `com.docker.compose.service` (present on every
container Compose creates) is the strong-evidence tier; an *exact*
container-name match is the only fallback -- never a fuzzy or
prefix-stripped guess. A duplicate match on either tier makes that
service_id's runtime state `UNKNOWN` with an `ambiguous_runtime_match`
warning, rather than silently picking a candidate.

Only an allowlisted subset of each container's fields is ever used:
`Labels` (matching only), `Status` (parsed into running/health), `Image`
(for the comparison below). No container ID, host PID, or Docker socket
detail is read or returned anywhere.

## Regression Health relationship

Regression Health is capability-oriented, not per-service -- DH-1's
discovery established this and DH-2 does not relitigate it. The response
carries only a **compact global context**: per-phase (`p0`/`p1`/`p2`)
`status`/`certification_status`, plus `freshness` -- reusing
`load_regression_health()` entirely and discarding `capabilities`,
`findings`, and `technical_debt` before they ever reach the response. No
service in the `services` array ever claims a Regression Health status;
there is no reliable RH-artifact-to-service_id mapping to make that claim
safely.

## Prometheus status

`analytics.prometheus` (the existing, already-tested client) is reused
as-is -- no new Prometheus client was written. As of this milestone there
is no scrape config, `prometheus.yml`, or per-service job/instance
labeling anywhere in this workspace (confirmed by that module's own
docstring), so there is no reliable evidence connecting a Compose
service_id to a specific Prometheus target. DH-2 therefore reports only a
**global** `data_sources.prometheus` flag (`not_configured` when
`PROMETHEUS_URL` is unset, else `available`/`unavailable` from a bare `up`
instant query) and adds no per-service Prometheus field. Per-service
target correlation is deferred, not silently skipped -- it needs real
scrape configuration to exist first.

## Deployment/image comparison

`deployment_health_runtime.compare_image` is conservative by construction:
any ambiguity -- missing data on either side, an unresolved `${VAR}`,
either side untagged, either side `latest` -- resolves to `UNKNOWN` rather
than a guessed `MATCH`/`MISMATCH`. `latest` is never treated as a verified
version (mirrors DH-1's own image-parsing rule). Repository comparison
normalizes Docker Hub's implicit `library/` namespace (so
`mysql:8.0` == `docker.io/library/mysql:8.0`) but nothing more elaborate.
No git revision, source commit, release version, build timestamp, or
image-digest-as-proof-of-build is claimed anywhere -- DH-2 only ever
compares the two literal image references it actually has.

## Failure semantics

`DeploymentHealthUnavailable` (DH-1's own error type; not resignaled) is
the only thing that fails the whole endpoint -- a missing/invalid/
unreadable Compose file, or `DEPLOYMENT_HEALTH_COMPOSE_PATH` unset,
returns the same safe shape `regression_health.py`'s own endpoint uses:

```
HTTP 503
{"status": "STATUS_UNAVAILABLE", "message": "Deployment health data is unavailable."}
```

Never the configured path, the underlying exception, or a stack trace.
Every other source failing (Docker down, probe config missing, Prometheus
unreachable, Regression Health unavailable) degrades that one
`data_sources` entry and nothing else -- proven directly in
`test_routes_deployment_health.py` and
`test_deployment_health_runtime.py::test_docker_unavailable_never_becomes_healthy`.

## Security / redaction

Every response field is built by an explicit allowlist in
`deployment_health_runtime._service_view`/`build_deployment_health_response`
-- never a recursive dump of a Docker or Compose object. No credential,
password, token, JWT, API key, environment value, secret value, container
ID, host PID, Slurm job ID, backend handle, Docker socket path, absolute
host path, private mount path, or tenant-private data is read from any
source, let alone returned. Verified two ways: unit tests assert forbidden
markers are absent from serialized JSON (including a container dict with
a real-shaped fake container ID attached, to prove the allowlist -- not
just "nothing sensitive was in the input" -- is what's doing the work),
and the real 41-service/real-Docker/real-config live check (`section 28`
of the implementation record) was grepped for the same markers on its
actual 68.7KB payload: zero hits.

## DH-1 contract change

One smallest-justified change to `deployment_health.py` itself: four new
`EvidenceSource` members (`DOCKER_INSPECT`, `HTTP_PROBE`, `PROMETHEUS`,
`REGRESSION_ARTIFACT`) were added to the existing enum -- exactly what
that module's own docstring reserved this extension point for. Nothing
else in DH-1 changed; all 53 of its existing tests still pass unmodified.

## DH-3 boundary

DH-2 provides a stable, versionable JSON contract for DH-3's
`Operations -> Infrastructure -> Deployment Health` page
(`/deployment-health`) to render. DH-3 is not started: no frontend file,
no navbar change, no new page.

## DH-4 boundary

DH-2's live read-only check (real Docker, real `config/control_center.yaml`
probes, real absence of Prometheus/Regression Health in this dev
environment) is a **development-environment integration check**, not a
credentialed production certification run. Wiring
`DEPLOYMENT_HEALTH_COMPOSE_PATH` to the actual deployed Compose baseline,
any real end-to-end credentialed verification, and multi-file Compose
overlay resolution remain DH-4 (and DH-1's own documented gaps).
