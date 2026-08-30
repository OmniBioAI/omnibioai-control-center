# Deployment Health -- DH-4: live deployment and certification

DH-4 deployed the `feat/deployment-health` branch to the actual running
Control Center (`omnibioai-studio-control-center-1` /
`omnibioai-studio-control-center-web-1`) and certified DH-1/DH-2/DH-3's
promised behavior against it. Everything below was verified against the
live, deployed system -- not inferred from source or automated tests alone.

## Deployment

- **SPA route**: `/deployment-health` (nginx `location /` SPA fallback).
- **API route**: `/deployment-health/data`, rewritten by nginx to the
  backend's `GET /deployment-health` -- verified live, distinct from the
  SPA route (no REG-010 recurrence).
- **Permission**: `platform.manage_infra`, on the deployed backend, gating
  the real route registration.
- **Compose baseline**: `DEPLOYMENT_HEALTH_COMPOSE_PATH=/workspace/omnibioai-studio/docker-compose.yml`,
  `DEPLOYMENT_HEALTH_BASELINE_SOURCE=development`,
  `DEPLOYMENT_HEALTH_DEPLOYMENT_REPOSITORY=omnibioai-studio` -- three
  environment variables on the existing `control-center` service in
  Studio's `docker-compose.yml`. **No new mount** was added: `${MACHINE_DIR}:/workspace`
  already made this file readable at this exact path, for unrelated,
  pre-existing reasons. Confirmed authoritative by reading the live
  container's own `com.docker.compose.project.config_files` label:
  exactly this one file, no overlay.
- **Docker access**: unchanged, reused as-is. `control-center`'s
  `DOCKER_HOST` already pointed at `docker-socket-proxy`
  (`unix:///var/run/proxy-socket/docker.sock`), confirmed by this repo's
  own pre-existing compose comment that the proxy's endpoint allowlist
  already covers exactly what `routes_docker.py` needs (`docker ps[-a]`,
  `docker inspect`, `docker images`) with zero DH-4 changes to the proxy's
  allowlist.

## Certification result

**DEPLOYMENT HEALTH V1 CERTIFIED.**

- Live authorization matrix: anonymous 401, authenticated-without-permission
  403, authorized 200 -- all three verified against the deployed origin
  with real (disposable) identities, not automated tests.
- Real 41-service inventory: 41 services, 0 duplicate IDs, 87 dependency
  edges, 12 correctly-UNKNOWN third-party ownerships, 0 UNKNOWN
  categories, summary counts sum to total.
- Intrinsic vs. effective health: preserved as two distinct values on
  every service; a naturally-occurring HARD-dependency-UNKNOWN case
  (`tes`/`toolserver` → `deploy-verify`, a one-shot init container) and a
  fixture-constructed HARD-dependency-UNHEALTHY case (see below) both
  verified live, in both directions, without ever rewriting a service's
  own intrinsic health.
- Docker-unavailable, Compose-missing, Compose-invalid, and Regression-
  Health-unavailable fixtures: all verified live via safe, reversible,
  single-service mechanisms (a docker-exec environment override, or a
  scoped Compose env-var change with a single-service recreate) --
  no other service was ever stopped or restarted. Every fixture was
  restored and re-verified against the real baseline afterward.
- Prometheus: confirmed still `not_configured` in this deployment, exactly
  as DH-2 documented (deferred, not added here).
- Image comparison: live evidence of real `MATCH` results (pinned tags:
  `mysql:8.0`, `redis:7-alpine`, `neo4j:5.15`, the three dev-tool images)
  and `UNKNOWN` for build-only/untagged/`latest` services -- `latest`
  never treated as a verified match.
- Read-only: `POST`/`PUT`/`DELETE` against the live `/deployment-health`
  all return 405. No control of any kind exists on the page.

## Live-testing-justified fix

One genuine defect was found and fixed during live certification (Section
17/18 fixtures), in `routes_docker.py::get_containers_status()` -- code
DH-2 reuses verbatim, not code DH-2 wrote. `subprocess.run` doesn't raise
on a nonzero exit code, so a `docker` CLI unable to reach its daemon
(confirmed live with a deliberately broken `DOCKER_HOST`) used to fall
through to the success path with empty stdout, silently reported as "0
containers running" rather than an error -- `data_sources.docker` read
`"available"` under this condition. Fixed with a `result.returncode != 0`
check (2 new focused tests added, all existing tests -- including the
legitimate "genuinely zero containers, exit 0" case -- still pass
unchanged). Re-verified live after the fix: `data_sources.docker` now
correctly reads `"unavailable"` under the same broken-`DOCKER_HOST`
condition, with no fabricated `HEALTHY` anywhere in the response.

Note throughout: this defect never caused an unsafe fabrication --
every affected service's `runtime.present` was already `False`, so
`intrinsic_health()`'s own precedence rules already, correctly, never
produced `HEALTHY` from a missing Docker source. The defect was in the
`data_sources.docker` diagnostic label's accuracy, not in the safety
invariant itself.

## Deployment topology (for operators)

```
Studio docker-compose.yml (development baseline, single file, no overlay)
        |  (already-existing ${MACHINE_DIR}:/workspace mount, read-write,
        |   pre-existing/unrelated to DH-4)
        v
control-center container: DEPLOYMENT_HEALTH_COMPOSE_PATH points into it
        |
        v
DH-1 parser -> DH-2 runtime aggregator (Docker via the existing proxy,
        application probes via config/control_center.yaml, Regression
        Health via the existing REGRESSION_HEALTH_ARTIFACT_PATH mount)
        |
        v
GET /deployment-health (platform.manage_infra) -> DH-3 Admin Console page
```

## Known, unchanged limitations (not new to DH-4)

- No multi-file Compose overlay resolution (DH-1's own documented gap;
  this deployment's baseline is a single file, so it doesn't apply here).
- Prometheus per-service correlation remains deferred (no scrape config
  exists anywhere in this workspace).
- Source/commit/build-timestamp drift remains out of scope (DH-5).
