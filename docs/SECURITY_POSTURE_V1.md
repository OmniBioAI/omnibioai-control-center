# Security Posture V1

## Purpose

Security Posture is a read-only, evidence-backed view of controls across the
OmniBioAI ecosystem. It answers what is implemented, tested, live-validated,
certified, fresh, or unknown. It does not calculate a score and does not
replace specialized administration surfaces.

Security Overview remains the operational dashboard. Security Posture is the
cross-service verification model. Existing security, audit, compliance, MFA,
SSO, session, and service-identity pages remain in place.

## Model

The pure model is `control_center.security_posture`. It accepts explicit,
already-collected evidence and has no HTTP, network, Docker, Auth, database,
Redis, or filesystem-discovery behavior. Its frozen dataclasses serialize only
allowlisted fields in deterministic order.

Control categories are `IDENTITY`, `AUTHENTICATION`, `AUTHORIZATION`,
`TENANT_ISOLATION`, `GATEWAY`, `POLICY`, `COMPUTE_GOVERNANCE`,
`CONTAINER_SECURITY`, `AUDIT`, `SECRET_MANAGEMENT`, and `CERTIFICATION`.

## Status dimensions

Implementation uses `IMPLEMENTED`, `NOT_IMPLEMENTED`, and `UNKNOWN`.
Tests use `PASS`, `FAILED`, `PARTIAL`, `NOT_RUN`, and `UNKNOWN`.
Live state uses `AVAILABLE`, `UNAVAILABLE`, `PARTIAL`, and `UNKNOWN`.
Certification uses `CERTIFIED`, `NOT_CERTIFIED`, `PARTIAL`, and `UNKNOWN`.
Freshness uses `CURRENT`, `STALE`, and `UNKNOWN`.

Overall posture is one of `VERIFIED`, `PARTIAL`, `ATTENTION`, `UNKNOWN`, or
`NOT_IMPLEMENTED`. These dimensions are never collapsed into one status.

## Posture calculation

- `NOT_IMPLEMENTED` implementation produces `NOT_IMPLEMENTED`.
- An active issue or failed test produces `ATTENTION`.
- Conflicting evidence of the same type produces `UNKNOWN`.
- Implemented, passing tests, available live evidence, certified evidence,
  and current freshness produce `VERIFIED`.
- Passing tests without live or certification evidence produce `PARTIAL`.
- Missing evidence never produces `PASS` or `VERIFIED`.
- Stale certification remains `CERTIFIED`, while overall posture is no
  stronger than `PARTIAL`.
- Unavailable live state produces `ATTENTION` only when the control declares
  live availability to be required; otherwise it remains conservatively
  `PARTIAL`.

## Evidence

Supported evidence types are `SOURCE_IMPLEMENTATION`, `UNIT_TEST`,
`INTEGRATION_TEST`, `LIVE_VALIDATION`, `REGRESSION_CERTIFICATION`,
`RUNTIME_HEALTH`, `CONFIGURATION`, `SECURITY_AUDIT`, `COMPOSE_SECURITY`, and
`DOCKER_PROXY_POLICY`.

Evidence includes only repository, identifier, status, authoritative
validation time, freshness, and a short redacted description. Arbitrary raw
metadata is not accepted or serialized.

## Findings and technical debt

Findings are explicitly typed as `ACTIVE_ISSUE`, `FIXED_HISTORICAL`,
`TECHNICAL_DEBT`, or `COVERAGE_GAP`. Fixed regression findings remain useful
evidence and do not become active incidents. Severity is included only when
supplied by the source.

## Freshness and source availability

Timestamps must be timezone-aware ISO-8601 values. Missing or malformed
timestamps do not receive a fabricated value. Source availability is a
status-only map using `AVAILABLE`, `UNAVAILABLE`, `UNKNOWN`,
`NOT_CONFIGURED`, or `PARTIAL`.

The intended source identifiers are `auth`, `gateway`, `policy`, `hpc_policy`,
`security_audit`, `docker_proxy`, `regression_health`, and `secret_scan`.
SP-1.1 does not query these sources.

## Known limitations

- Auth revocation has a documented Redis blacklist fail-open path while
  database and user-state checks remain fail-closed.
- Docker Socket Proxy protection has Compose evidence, but standalone proxy
  source evidence was unavailable during discovery.
- Organization isolation is certified for exercised paths, not automatically
  for every ecosystem service.
- The `isolation.organization` control preserves `CERTIFIED` for the promoted
  exercised-path capability, but its overall posture is `PARTIAL`. `CERTIFIED`
  does not imply platform-wide coverage; that requires explicit broader
  evidence.
- Audit correlation is partial until backend/remote-handle enrichment exists.
- Secret-scan evidence is not normalized across repositories.
- Policy counters, audit lag, and promoted regression-to-control mappings are
  future contracts, not model behavior.

These limitations are represented as evidence gaps or control limitations;
they are not fabricated failures.

## Security and redaction

Public strings are defensively validated. Serialization cannot carry
credentials, secrets, token material, JWT values, authorization headers, API
keys, cookies, private keys, absolute private paths, container IDs, backend
handles, usernames, or tenant-private identifiers. No arbitrary nested input
is recursively serialized.

## V1 inventory

P0 controls include signed credential validation, issuer/audience and expiry,
revocation, RBAC/ABAC, organization isolation, gateway enforcement and
context propagation, policy fail-closed behavior, Docker socket/proxy
protection, audit signing/delivery, and regression certification.

P1 controls include MFA, SSO, header sanitization, HPC resource governance,
audit correlation, and secret scanning.

Definitions are neutral: no current PASS, certification, or runtime state is
hard-coded into the inventory.

## Backend integration (SP-2)

SP-2 adds `security_posture_backend.py` and the protected read-only
`GET /security-posture` route. The assembler reuses the existing Control
Center service checker and the promoted Regression Health loader. Adapters
retain only normalized availability, explicit capability statuses, safe
timestamps, and allowlisted evidence; raw upstream dictionaries and errors
are never returned.

Regression capabilities are mapped only where the artifact has an explicit
control relationship: tenant isolation, audit correlation, and gateway
context propagation. Fixed promoted findings remain historical findings.
Runtime health is represented separately for Auth, Gateway, Policy, HPC
Policy, and Security Audit. Docker proxy and credential-scan evidence remain
partial because their complete source contracts are unavailable.

The route uses the existing `manage_all_orgs` platform-admin permission. It
defines GET only; no mutation endpoint is present. Optional source failures
degrade individual source/control states. Assembly failures return a generic
503 response without paths or upstream details.

SP-3 may consume this endpoint from the frontend. SP-2 intentionally changes
no frontend, navigation, nginx, Compose, or upstream service.

The authorization recommendation is to reuse the existing `manage_all_orgs`
platform-admin pattern used by Security Overview, Audit Logs, Compliance, and
platform-wide identity/security data. This is a recommendation only; it is
not implemented by SP-1.1.

## Admin Console integration (SP-3)

The Admin Console page is `/security-posture`; its browser data request is
`GET /security-posture/data`. Nginx rewrites only that exact data path to the
backend's protected `GET /security-posture`, leaving `/security-posture` as an
SPA deep link. Navigation places Security Posture immediately after Security
Overview in the Security group and uses the existing `manage_all_orgs`
visibility signal. Backend authorization remains authoritative.

The page renders backend-calculated categorical summary counts, a dynamic
control table, independent implementation/test/live/certification/freshness
dimensions, expandable safe evidence and finding details, limitations, and
source availability. It has no score and no mutation or remediation controls.
401, 403, 503, malformed, and network responses render safe non-green states;
raw upstream responses and errors are not displayed. Security Overview remains
the operational activity dashboard; Security Posture is the cross-service
evidence view.

SP-4 is the live-certification boundary: authenticated/unauthorized behavior,
deployed SPA deep links, source-unavailable fixtures, stale certification,
recovery, and deployed redaction still require validation. No live
certification is performed in SP-3.
