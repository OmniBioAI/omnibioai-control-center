# Deployment Health -- DH-5: source / commit / image drift detection

DH-5 is a read-only, additive extension of the already-certified
Deployment Health V1 (DH-1--DH-4). It adds one new operational
dimension -- **drift**, whether a service's *running* artifact still
matches its *configured* artifact -- next to, and never merged into,
the existing intrinsic/effective **health** dimension. Nothing in DH-5
restarts, rebuilds, redeploys, pulls, or mutates any container, image,
Git checkout, or Slurm/K8s resource; it only reads already-available
evidence and reports a classification.

## Why drift, and why it's separate from health

A service can be perfectly healthy (its container is up, its
healthcheck passes, its application probe responds) while running a
stale image -- e.g. rebuilt locally but never recreated, or its
`docker-compose.yml` `image:` reference bumped without redeploying.
Health says nothing about that. Drift does, and only that -- it never
changes a service's intrinsic or effective health, and health never
changes drift.

## The four drift states

| Status          | Meaning                                                                 |
|-----------------|--------------------------------------------------------------------------|
| `match`         | The running container's resolved image ID matches the image currently tagged with the service's configured reference. |
| `drifted`       | They resolve to different image IDs -- most commonly: rebuilt locally without being recreated. |
| `unknown`       | Not enough evidence exists to compare (no running container, no resolvable local image, a build-only service with no explicit `image:` key, malformed metadata). |
| `not_applicable`| The service has no OmniBioAI repository ownership evidence (DH-1's own finding) -- third-party infrastructure (MySQL, Redis, Prometheus, etc.) with nothing of ours to compare against. |

`unknown != drifted`, `unknown != unhealthy`, `drifted` never implies
`unhealthy`, and `not_applicable` is never rendered as a failure. A
service can be `HEALTHY` + `MATCH`, `HEALTHY` + `UNKNOWN`,
`HEALTHY` + `DRIFTED`, or `DEGRADED` + `MATCH` -- all four combinations
are representable, because health and drift are computed, stored, and
rendered as two fully independent values.

## Evidence model

DH-5 compares three separate, un-collapsed sections, mirroring the
public API and the UI:

- **Source** (`source_version_for`): the service's repository (reused
  verbatim from DH-1's own ownership evidence -- never re-derived) and
  an `expected_revision`, populated only from a concrete evidence
  source. Verified against the real, live ecosystem before this was
  designed: **no current OmniBioAI-built image anywhere in this
  deployment carries an `org.opencontainers.image.revision` (git
  commit) label**, so `expected_revision` is honestly `unknown` for
  every real service today -- an architecture finding this module
  reports, not a bug it works around by guessing a commit from a
  timestamp, container uptime, or filesystem/name similarity (all
  explicitly forbidden).
- **Configured artifact** (`configured_artifact_for`): the service's
  configured `image:` reference, tag, and digest -- straight from DH-1's
  own `ImageReference` parsing, nothing new.
- **Running artifact** (`running_artifact_from_container`): four label
  values read from the same `docker ps` container dict DH-2 already
  fetches (no second Docker call): Compose's own
  `com.docker.compose.image` label (the exact resolved image ID Compose
  recorded when it created the container -- immutable, free, and
  already present), plus the three standard OCI labels
  (`.revision`/`.source`/`.version`) if the image happens to carry them.

Comparison (`compute_drift`) resolves the service's *configured*
reference to a *currently* locally-tagged image ID with one bounded,
deduplicated `docker image inspect` batch call
(`routes_docker.get_local_image_ids`, one new function reusing the
exact same Docker Socket Proxy path -- `GET /images/{name}/json` --
every other Deployment Health Docker call already uses; zero proxy
allowlist changes were needed), then compares that ID against the
running container's own `com.docker.compose.image` ID. Only resolved,
immutable image IDs are ever compared -- never a raw tag string.

## Why a mutable tag can never fabricate `match`

A configured `image:` reference is very often mutable (`:latest`, a
locally-built `-local` tag, or similar). `latest == latest` never
produces `match` by itself: the comparison always goes through a fresh
lookup of *which image ID is currently tagged that way*, and only
compares that ID against the running container's own recorded ID. If
that lookup can't resolve (nothing locally tagged that way, Docker
unavailable, a build-only service with no explicit `image:` key at
all -- never a guessed Compose-auto-generated name), the result is
`unknown`, never a fabricated `match`.

## API contract (additive, backward-compatible)

DH-5 extends the existing `GET /deployment-health` response -- no new
endpoint. Every DH-1--DH-4 field is unchanged; two additions:

- Each entry in `services[]` gains a `drift` object:
  ```json
  "drift": {
    "source": { "repository": "omnibioai-auth", "expected_revision": null, "revision_type": "unknown" },
    "configured": { "image": "ghcr.io/omnibioai/omnibioai-auth:latest", "tag": "latest", "digest": null },
    "running": { "image_id": "sha256:...", "revision": null, "source": null, "version": null },
    "drift": { "status": "match", "reason": "...", "evidence": [{ "source": "docker_inspect", "detail": "..." }] }
  }
  ```
- The top-level response gains `drift_summary`: `{"match": n, "drifted": n, "unknown": n, "not_applicable": n}`,
  a separate dimension from the existing `summary` (health) block --
  never merged into or replacing it.

`build_deployment_health_response()`'s new `local_image_ids` parameter
is optional and keyword-only, defaulting to `{}`: every existing caller
and test that doesn't pass it keeps behaving exactly as before.

## Failure semantics

A failure to determine drift degrades only the `drift` dimension to
`unknown` -- it never fails the endpoint (the only thing that fails the
endpoint is the same Compose/DH-1 failure that already did before
DH-5). Concretely: Docker unavailable -> every owned service's drift is
`unknown` (never `match`); `docker image inspect` failing, timing out,
or returning malformed JSON -> `get_local_image_ids` returns `{}`,
never raises; a missing or malformed container `Labels` string ->
parsed as empty, never raises; a third-party service -> always
`not_applicable`, regardless of Docker's own availability.

## UI

The existing Deployment Health page (`/deployment-health`) is extended,
not duplicated:

- The service table gains one compact **Drift** column (badge + short
  reason), next to the existing Health column -- never inside it.
- A new **Drift Summary** section (Matched / Drifted / Unknown / Not
  Applicable stat cards) sits alongside, not in place of, the existing
  health Summary section.
- The service detail panel gains a **Source / Commit / Image Drift**
  section: Source, Configured, and Running are three visually distinct
  sub-sections, plus the drift status/reason and its evidence list.
  Only the same allowlisted fields the API already exposes are ever
  rendered -- never a raw Docker inspect payload, a container ID, or a
  filesystem path.
- `StatusBadge` gained `match` (green, reuses `healthy`'s color),
  `drifted` (the app's existing `--purple` accent -- deliberately not
  red or amber, so it can never be mistaken for `unhealthy`/`degraded`),
  and `not_applicable` (the same neutral muted gray `not_configured` and
  other non-alarming statuses already use). `unknown` was already gray
  from DH-3 and is reused unchanged -- never green.
- No new navbar entry, no destructive or mutating control anywhere on
  the page (same read-only guarantee DH-3/DH-4 already certified).

## Security

- No raw Docker socket, no Docker Socket Proxy bypass, no proxy
  allowlist change (`GET /images/{name}/json` was already allowed).
- No container, image, Git, Slurm, or K8s mutation of any kind.
- No credentials, tokens, container environment, backend handles, raw
  Docker inspect payloads, usernames, or absolute filesystem paths are
  ever serialized -- only the same handful of allowlisted fields shown
  above, verified by dedicated redaction tests on both the backend and
  frontend.
- Authorization is unchanged: `platform.manage_infra`, the same
  dependency gating the rest of the endpoint.

## Real ecosystem results (read-only discovery against the live Studio baseline)

Run against the actual, live `docker-compose.yml` and real `docker ps`/
`docker image inspect` output on the deployed system (see the DH-5
certification report for the exact method and full per-service table):

- **41 services total** (same inventory DH-4 certified).
- **12 `match`** -- locally-built dev-tool and application services
  currently running the same image ID that's currently tagged with
  their configured reference (`toolserver`, `tes`, `lims`, `jupyter`,
  `rstudio`, `vscode`, `videos`, `auth-service`, `policy-engine`,
  `hpc-policy-engine`, `security-audit`, `api-gateway`).
- **0 `drifted`** -- expected for a stable development environment with
  no naturally-occurring rebuild-without-recreate at the time of
  discovery.
- **17 `unknown`** -- every one of these is a build-only OmniBioAI
  service with **no explicit `image:` key** in Compose (Compose
  auto-generates a project-scoped image name for these at build time,
  which DH-5 deliberately never guesses -- see "why a mutable tag can
  never fabricate `match`" above). This is an honest architecture
  finding, not a defect: these services simply don't offer the evidence
  DH-5 requires to compare, by their own Compose definition.
- **12 `not_applicable`** -- confirmed third-party infrastructure with
  no OmniBioAI repository ownership evidence (`mysql`, `redis`,
  `ollama`, `neo4j`, `opa`, `prometheus`, `grafana`, `cadvisor`,
  `redis-exporter`, `node-exporter`, `nginx-router`, `deploy-verify`).

No result was manipulated toward more `match` -- the high `unknown`
count is itself useful architecture evidence (most OmniBioAI services
are still built in place, not published/pinned images), reported
honestly rather than worked around.

## Known limitations (unchanged scope boundaries, not defects)

- **No git-commit evidence exists today.** Until an OmniBioAI image
  embeds `org.opencontainers.image.revision`, `expected_revision` (and
  therefore any Source-vs-running-revision comparison) stays `unknown`
  for every service. DH-5 deliberately does not read git HEAD from a
  sibling repository checkout via subprocess to work around this --
  that would be a new, unreviewed evidence-gathering mechanism, not
  reuse of existing infrastructure, and was explicitly out of scope.
- **Build-only services stay `unknown`** until they either publish a
  pinned image or DH-5's evidence model is deliberately extended to
  cover Compose-managed local builds (a design decision for a future
  milestone, not attempted here).
- No multi-file Compose overlay resolution (DH-1's own pre-existing
  gap; unaffected by DH-5).
- No historical drift trend/storage -- every drift result reflects the
  current moment only, matching DH-1--DH-4's own no-persistence design.
