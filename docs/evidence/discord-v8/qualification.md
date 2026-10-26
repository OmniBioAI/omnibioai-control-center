# Discord V8 infrastructure and live acceptance qualification

Date: 2026-10-24 (UTC date)

## Decision

**PARTIAL; production NO-GO.** The V7 software baseline remains 24/24 and
11/11 event mappings. V8 completed fresh software regression and available
isolated mock qualification, but channel identity, production credentials,
DGX Docker provenance, Docker service E2E, full crash matrix, rollback, live
canaries, and production authorization could not be verified. Production was
not modified.

## Evidence integrity and scope

- V7 `SHA256SUMS` was checked before this work; all listed files verified.
- V8 host inspection was run with `scripts/qualify_discord_v8.py --mode
  inspect --timeout 10`. Host architecture was `aarch64`; Docker context was
  `default`; Docker daemon access returned permission denied. The runner
  exited 1 and reported provenance `NOT_VERIFIED`.
- The runner's isolated-tests mode ran the configured complete backend suite
  and in-process mock flow. It does not create containers or contact Discord.
- The unprivileged runner initially timed out because this execution sandbox
  denies local test sockets. The isolated suite was then run with approved
  loopback access; it completed successfully. The first run was not counted as
  a test pass.
- Read-only environment inspection found the legacy alert setting present,
  but no channel-map setting and no source signing keys. Secret values were
  not emitted. Discord administrator/readback access and secret-manager
  write access were unavailable. GitHub secret metadata lookup failed due to
  network connectivity; GitHub secret state is therefore unknown, not
  inferred absent.

## Qualification matrix

| Requirement | V8 result | Evidence / limitation |
|---|---|---|
| Software implementation | 24/24 (100%) | V7 accepted baseline; no implementation rewrite |
| Event mappings | 11/11 | V7 route tests; V8 six-route mock flow |
| Source adapters | 7/7 implemented | V7 source contracts; production runtime configuration not present |
| Source runtime qualified | 0/7 production; 7/7 mocked contracts | No source credentials/runtime deployment verified |
| Legacy publishers | 5/5 software migration paths | V7 implementation and tests; deployment-level equivalence unverified |
| Community channels | 3/3 excluded from automation | Mock flow confirms no automated route |
| Automated channel presence | 1/6 presence-only | Legacy alert variable exists; destination identity not verified |
| Verified channel mappings | 0/6 | No Discord admin or webhook metadata/readback verification |
| Source credentials | 0/7 verified | No authorized secret-manager inventory/write access |
| Backend regression | 2,224 passed, 0 failed | Fresh V8 full configured suite with loopback permission; 601 warnings; 72 subtests |
| Backend statement coverage | 98.01% | 8,947/9,129; unchanged 98% threshold passes |
| RAG Discord tests | 10/10 passed | Fresh targeted suite |
| Workbench Discord tests | 14/14 passed | Fresh targeted suite; harmless plugin configuration warnings |
| Videos publication tests | 6/6 passed | Fresh targeted suite |
| Mocked six-route flow | PASS | Six automated routes; three community exclusions; not Docker E2E |
| IAM/security | PASS (isolated API stack) | V7 real routing-stack tests using isolated test identities; not production IAM config |
| Crash recovery | NOT_VERIFIED | Three prior subprocess cases pass; full 18-scenario matrix not run |
| ARM64 images / provenance | NOT_QUALIFIED / NOT_VERIFIED | Docker daemon denied; no immutable image digests or build attestations |
| Deployment configuration | NOT_VERIFIED | Host Docker/compose configuration inaccessible |
| Docker disposable E2E | BLOCKED | Docker socket permission denied |
| Isolated rollback | NOT_VERIFIED | Requires Docker-backed candidate/previous images and isolated persistence |
| Live canaries | 0/6 | No explicit live publishing approval or verified destinations |
| Production deployment | Not performed | No approval; production unchanged |

The 2,254 combined passing test count is 2,224 Control Center + 10 RAG + 14
Workbench + 6 Videos tests. It is not a unique cross-repository suite count
and does not include repeated focused subsets. Executed test failures: zero.

## Channel identity matrix

| Channel | Automation | Credential/config evidence | Guild/channel identity |
|---|---|---|---|
| announcements | Yes | Missing | Not verified |
| bug-reports | Yes | Missing | Not verified |
| feature-requests | Yes | Missing | Not verified |
| support | Yes | Missing | Not verified |
| tutorials | Yes | Missing | Not verified |
| omnibioai-alerts | Yes | Legacy setting present, channel-map entry unverified | Not verified |
| general | No | No automated mapping | Community identity not inspected |
| research-chat | No | No automated mapping | Community identity not inspected |
| show-and-tell | No | No automated mapping | Community identity not inspected |

Presence of `DISCORD_ALERT_WEBHOOK_URL` does not prove its channel destination.
No webhook URL or token is included in this evidence.

## Source credential contract

The V7 source identities and expected secret names remain authoritative:

| Source | Secret reference | Present/validated |
|---|---|---|
| GitHub | `DISCORD_EVENT_GITHUB_SECRET` | No |
| RAG | `DISCORD_EVENT_RAG_SECRET` | No |
| Workbench | `DISCORD_EVENT_WORKBENCH_SECRET` | No |
| Documentation | `DISCORD_EVENT_DOCUMENTATION_SECRET` | No |
| Video | `DISCORD_EVENT_VIDEO_SECRET` | No |
| Infrastructure | `DISCORD_EVENT_INFRASTRUCTURE_SECRET` | No |
| Support | `DISCORD_EVENT_SUPPORT_SECRET` | No |

Provision seven independent high-entropy keys in the approved secret manager,
inject only each source's own key, and validate signing/rotation/replay
behavior without exposing key material. No keys were generated or stored by
this workstream.

## V8 release gates

| Gate | Status | Basis |
|---|---|---|
| G1 central router | PASS | V7 baseline and fresh backend/mocked route tests |
| G2 event mappings | PASS | 11/11 existing mappings, route test coverage |
| G3 channel identities/config | BLOCKED | 0/6 verified; missing configuration/admin access |
| G4 seven authenticated source runtimes | BLOCKED | 7/7 implementations, but 0/7 production credentials/runtime config |
| G5 legacy publisher migration | PASS | 5/5 software paths; deployment-level equivalence remains unverified |
| G6 IAM/security | PASS | Isolated real FastAPI authorization tests; production identity integration not asserted |
| G7 reliability/crash recovery | NOT_VERIFIED | Full process-level failure matrix absent |
| G8 backend regression/coverage | PASS | 2,224 pass; 98.01% coverage, threshold 98% |
| G9 ARM64 provenance/deployment | BLOCKED | Docker daemon permission denied; no provenance evidence |
| G10 six live canaries | BLOCKED | No approval, verified hooks, or authorized readback |
| G11 isolated rollback | BLOCKED | Docker access unavailable |
| G12 explicit production approval | BLOCKED | Not provided; no deployment attempted |

Passed gates: 5/12 (41.7%). This is not overall technical qualification; the
release remains blocked by mandatory gates.

## V8 runner and operator checklist

New file: `scripts/qualify_discord_v8.py`. Default mode performs bounded,
read-only Docker inventory, never reads container env, and filters Docker
errors. `--mode isolated-tests` runs backend regression and in-process mock
flow. Neither mode sends live messages, modifies production, or qualifies a
Docker E2E stack. On the current host the runner failed closed as expected.

Required operator actions, in order:

1. Discord administrator: provision six distinct webhooks in the intended
   guild for the six automated channels. Store references in the approved
   secret manager under the `DISCORD_CHANNEL_WEBHOOKS` map; preserve the
   alert fallback until the alerts destination is proven. Verify guild,
   channel, and permissions using webhook metadata, not a test post. Keep the
   three community channels out of the map.
2. Secret-manager operator: provision the seven independent source keys in
   the table above; bind each key only to its source, validate rotation and
   rejection paths. Do not paste secrets into shell history or reports.
3. DGX administrator: grant the designated operator authorized read-only
   Docker access (do not chmod the socket). Run `python3
   scripts/qualify_discord_v8.py --mode inspect --timeout 30`; independently
   verify immutable image digests, source commits/build attestations, compose
   and secret references, health, persistence, and ARM64 architecture.
4. With isolated Docker authority, run the disposable six-route E2E and
   18-scenario subprocess crash matrix, then qualify rollback using isolated
   state only. These qualifications are not production operations.
5. Obtain explicit approval for the exact six synthetic canary payloads and
   destinations. Send once per channel and verify actual visible delivery,
   sanitized receipts, deduplication, and no cross-channel delivery.
6. After technical gates and canaries pass, obtain separate explicit
   production deployment approval. No deployment is authorized by this
   workstream.

## Production status

Production changed: **No**. Live messages sent: **No**. Deployment performed:
**No**. Production readiness: **No-Go**. Highest-priority next action is
operator provisioning and identity verification for the six channel hooks
and seven source secrets using the approved secret manager; without that,
source and channel production qualification cannot begin.
