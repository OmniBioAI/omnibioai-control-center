# OmniBioAI Discord V10 release-candidate qualification

Date: 2026-10-24

## Decision

**PARTIAL; candidate UNSTABLE; production NO-GO.** This is the current dirty
cross-repository candidate, fingerprinted in `release-candidate-manifest.json`.
No commit, merge, deployment, credential write, Docker permission change,
Discord administrative action, or live canary was performed. Production is
unchanged. The worktree changes that predate V10 remain intact.

Current counts: 24/24 software implementation items remain present at source
level; 11/11 event mappings pass focused tests; legacy publisher status is
4/5 migrated or safely retired (conservative V2 classification); one of six
credential names is present only as a legacy-alert setting, but 0/6 channel
identities are verified; source credentials/configuration/runtime are 0/7;
119 focused Control Center tests pass, while full regression and coverage are
not available. Only G1 and G2 pass (2/12, 16.7%).

## Baseline reconciliation and candidate identity

V2 reported 112 focused Discord passes and 4/5 legacy publishers migrated or
safely retired. V9 reported 109 focused passes and 2/12 gates for its then-
current worktree. V8 reported 2,224 backend passes, 98.01% coverage and 5/12
gates. Those reports do not describe an identical working tree and are not
combined as V10 evidence. Recorded source HEADs are still the V9 SHAs, but
all participating source repositories are dirty; Docs is three commits
behind upstream. Exact branches, SHAs, staged/modified/deleted/untracked
paths, dependency declarations, and working-tree fingerprints are in the
candidate manifest. Nothing was reset or staged.

V10 changes since V2/V9 are limited to evidence-backed hardening and
qualification: channel webhook-ID/legacy-alias and port validation; tests for
those cases and cross-channel isolation; additional real subprocess
termination/concurrency/database-lock tests; correction of Workbench's
`dotenv` requirement name to `python-dotenv`; and this evidence/runbook
update. The focused count is 119, not an accumulation of V2/V9 counts.

## Candidate environment and dependency reproducibility

The execution host is `spark-c275`, Linux `aarch64`; no container marker is
present, so it appears to be a host session, but DGX hardware identity was not
read from a device model file. Docker CLI uses context `default`; the V8
read-only inspector gets permission denied from the daemon. This may be a
session isolation boundary and does not establish the permission of a
separately authorized DGX operator. No privilege escalation or socket change
was attempted.

No lockfiles exist for the tested Python repos. The existing Control Center
virtualenv lacks pytest and has dependency versions outside backend
constraints. System Python has pytest but lacks pytest-asyncio, pytest-cov,
FastAPI/Starlette, and python-dotenv. An isolated install from the declared
backend dev extra failed at PyPI DNS resolution. No mixed or unpinned
environment was accepted as qualification. Exact versions, failed install,
test commands and outcomes are in `test-results.md`.

## Six-channel evidence matrix

| Automated destination | Config presence | Guild/channel/webhook association | Current route evidence |
|---|---|---|---|
| announcements | Missing | Not verified | Mock route PASS |
| bug-reports | Missing | Not verified | Mock route PASS |
| feature-requests | Missing | Not verified | Mock route PASS |
| support | Missing | Not verified | Mock route PASS |
| tutorials | Missing | Not verified | Mock route PASS |
| omnibioai-alerts | Legacy variable name present only | Not verified; actual destination unknown | Mock route PASS |

Overall: `CHANNELS_CONFIGURED=1/6` presence-only, `VERIFIED_CHANNEL_MAPPINGS=0/6`.
No secret value, complete webhook URL, guild ID, or channel ID was read into
this report. Code rejects malformed endpoints, nonstandard ports, unknown or
community route names, repeated webhook IDs, and a legacy alert webhook ID
aliased to another route. That syntax validation does not establish that a
well-formed webhook belongs to its named Discord channel. Community channels
`general`, `research-chat`, and `show-and-tell` remain unroutable.

Least-privilege permissions and actual webhook-to-channel ownership require
Discord admin metadata verification, which is unavailable here.

## Seven-source credentials and runtime matrix

| Source | Secret reference | Key independently verified | Runtime injected/qualified |
|---|---|---:|---:|
| GitHub | `DISCORD_EVENT_GITHUB_SECRET` | No | No |
| RAG | `DISCORD_EVENT_RAG_SECRET` | No | No |
| Workbench | `DISCORD_EVENT_WORKBENCH_SECRET` | No | No |
| Documentation | `DISCORD_EVENT_DOCUMENTATION_SECRET` | No | No |
| Video | `DISCORD_EVENT_VIDEO_SECRET` | No | No |
| Infrastructure | `DISCORD_EVENT_INFRASTRUCTURE_SECRET` | No | No |
| Support | `DISCORD_EVENT_SUPPORT_SECRET` | No | No |

The Studio Compose file maps the channel map and source verifier variables to
Control Center and maps source keys to RAG/Workbench service environments;
workflow/CLI contracts exist for GitHub, Videos, Docs, Infrastructure, and
Support. These are wiring contracts, not evidence that production values are
stored or injected. The active Studio `.env` has only the legacy alert key
name; values were not read. No approved secret manager CLI or integration is
available. `SOURCE_CREDENTIALS=0/7`, `SOURCE_PRODUCTION_CONFIGURED=0/7`,
`SOURCE_RUNTIME_QUALIFIED=0/7`.

## Five legacy publisher paths

| Path | V10 disposition | Current evidence / remaining qualification |
|---|---|---|
| RAG | Central signed client; old successful-query community notices removed; only sanitized service failures are emitted | Source tests not executable without pytest-asyncio; no runtime key |
| Workbench | User/email/pipeline notifications safely retired as community posts; explicit signed public-event client and stable queued task remain | Test setup blocked by `python-dotenv` environment; no source key or verified caller |
| Documentation | Central client when router and documentation key are configured; direct webhook fallback only when central path is unavailable | Bash syntax pass; no runtime secret/receipt |
| Ecosystem build shell | Central client when configured; old alert fallback retained only when central route/key is absent | Bash syntax pass; no runtime secret/receipt |
| Control Center alerts | Central-first when router and infrastructure key exist; `DISCORD_ALERT_WEBHOOK_URL` retained as compatibility fallback | 119 focused tests; actual legacy destination/replacement equivalence unverified |

V2's 4/5 count means four paths migrated or safely retired; the fifth is the
preserved Control Center alert fallback. V8's 5/5 refers to software path
support and counted the central-first/fallback implementation as migrated.
V10 uses 4/5 for operational migration, and does not remove the fallback to
improve the count. Central/legacy code avoids dual send: once a central
submission is attempted it does not fall back after rejection, timeout, or
ambiguous acceptance. Production delivery equivalence remains unverified.

## Local reliability and process recovery

The 119 focused tests cover all 11 event mappings and six routes using mock
responses; source/event authorization contracts; malformed configuration;
duplicate webhook IDs including legacy aliasing; 2xx, permanent 4xx, 429 and
bounded `Retry-After`, ambiguous 5xx, connect/read failure; stable-ID
idempotency; mention suppression; metadata-only DLQ/redaction; durable event
records; approval/reconciliation; and explicit local replay. A failure on
one route does not stop a subsequent unrelated route.

Seven subprocess crash tests use temporary durable SQLite and real OS process
termination. They cover crash before persistence, after claim/before HTTP,
during mocked submission, after mocked remote acceptance before local
receipt, pending/ambiguous restart, concurrent claims, restart during a
retry, and a database lock. Unit failure injection covers 429/5xx/network,
DLQ and local replay. Ambiguous requests are never automatically retried;
exactly-once delivery is not claimed.

`CRASH_RECOVERY=NOT_VERIFIED` for the complete acceptance gate: the
IAM-protected replay/reconcile APIs, real container worker/service restart,
and Docker-backed failure matrix could not be executed. Local process test
passes are not a substitute for that full stack.

## ARM64, Docker E2E, rollback, and live canary status

- Host architecture is aarch64, but no candidate image was inspected. No
  immutable digest, build attestation, source-to-image binding, active
  runtime secret reference, persistent volume, or health/log/metric behavior
  was verified. `ARM64_IMAGES=NOT_QUALIFIED`, provenance `NOT_VERIFIED`.
- `docker compose config --quiet` passes statically. The V8 Docker inspector
  reports daemon permission denied, so no containers were enumerated. The
  in-process runner's 6/6 route and 3/3 community exclusion mock passed, but
  it is **not** disposable Docker E2E. Docker E2E is blocked.
- No candidate/previous-image rollback was performed; rollback is
  `NOT_VERIFIED`.
- No live canary was sent. No Discord admin/readback or explicit publication
  authorization exists here. `LIVE_CANARIES_PASSED=0/6`.
- Production deployment approval was not granted; deployment was not
  attempted. Production is unchanged.

### Prepared canary drafts (not sent)

All use synthetic text with no user, patient, customer, or incident data.
The IDs below are reserved draft IDs and have not been submitted. For any
authorized run, use a new unique run suffix, sign with the source's
independent production key, submit with `approved_publication=false`, obtain
central IAM operator approval, and verify the destination by Discord
readback.

| Channel | Draft event ID | Source / event | Draft title and message |
|---|---|---|
| announcements | `v10-canary:announcements:20261024-01` | GitHub / `platform.release` | `TEST ONLY — V10 announcement canary`; `Synthetic release notification; this is not a product release.` |
| bug-reports | `v10-canary:bug-reports:20261024-01` | GitHub / `github.issue.confirmed` | `TEST ONLY — V10 bug-report canary`; `Synthetic confirmed-issue route check; no real issue or customer is involved.` |
| feature-requests | `v10-canary:feature-requests:20261024-01` | GitHub / `feature.request.accepted` | `TEST ONLY — V10 feature canary`; `Synthetic approved-feature route check; no real request is being announced.` |
| support | `v10-canary:support:20261024-01` | Support / `support.incident` | `TEST ONLY — V10 support canary`; `Synthetic service notice; no customer ticket or incident exists.` |
| tutorials | `v10-canary:tutorials:20261024-01` | Documentation / `documentation.published` | `TEST ONLY — V10 tutorial canary`; `Synthetic documentation route check; no documentation release occurred.` |
| omnibioai-alerts | `v10-canary:omnibioai-alerts:20261024-01` | Infrastructure / `infrastructure.alert` | `TEST ONLY — V10 alerts canary`; `Synthetic operational alert route check; no active incident exists.` |

## V10 gate decisions

| Gate | Status | Basis |
|---|---|---|
| G1 Central router | PASS | Fresh focused tests and in-process route flow |
| G2 Event mappings | PASS | All 11 mappings route to the fixed six destinations under mocks |
| G3 Six verified channels | BLOCKED | 0/6 identity readbacks; legacy alert destination unknown |
| G4 Seven authenticated source runtimes | BLOCKED | 0/7 credentials/configured runtimes |
| G5 Legacy migration/compatibility | NOT_VERIFIED | Source audit complete; full cross-repo/runtime equivalence unavailable; alerts fallback retained |
| G6 IAM security | NOT_VERIFIED | IAM/API suite blocked by missing FastAPI in the available test environment |
| G7 Full crash recovery | NOT_VERIFIED | Local process suite passes; API/container full matrix not run |
| G8 Full regression and 98% coverage | BLOCKED | Full suite could not start; no V10 coverage measurement |
| G9 ARM64 provenance/config | BLOCKED | No Docker daemon/image provenance access |
| G10 Six approved live canaries | BLOCKED | No explicit authorization or verified destination IDs |
| G11 Disposable rollback | BLOCKED | Requires Docker-backed isolated stack |
| G12 Explicit production approval | BLOCKED | Not provided |

**Gates passed: 2/12. Technical qualification: BLOCKED. Production ready:
NO. Production deployed: NO. Production unchanged: YES.**

## Consolidated operator checklist

1. Discord administrator: create or verify one least-privilege webhook per
   automated channel in the approved guild. Read back guild/channel/webhook
   IDs and association; prove six distinct destinations, no community IDs,
   and that the legacy alert webhook actually maps to `omnibioai-alerts`.
   Store webhook secrets only in the approved secret manager.
2. Secret-manager operator: provision seven independent source keys under
   the exact references in the table, configure each runtime with only its
   own key and the router verifier, and verify signature, replay, isolation,
   rotation, and rejection behavior without printing values.
3. Authorized DGX operator, read-only first:
   `cd /home/manish/Desktop/omnibioai-ecosystem/omnibioai-control-center && python3 scripts/qualify_discord_v8.py --mode inspect --timeout 30`
   Capture image digests/provenance, Compose values by reference only,
   persistent state, health, logs, and metrics. Do not chmod the socket.
4. In disposable isolated Docker only, run the backend/IAM, seven-source,
   six-route E2E and full crash matrix; then roll back to the prior digest
   and verify pending/ambiguous state, schema compatibility, and alert
   compatibility. Never attach production writable storage.
5. After explicit live-canary authorization, send the six drafts once and
   verify visible message/channel IDs, sanitized receipts, deduplication,
   and no cross-channel delivery. Obtain a separate production approval only
   after G1-G11 pass.
6. Resolve Docs' three-commit upstream lag by owner review, create supported
   resolved dependency locks in isolated environments, rerun all affected
   suites and the >=98% Control Center coverage gate, then freeze/commit the
   reviewed candidate. Do not merge or deploy without authorization.
