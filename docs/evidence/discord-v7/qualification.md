# OmniBioAI Discord V7 qualification

Qualification date: 2026-10-24. This is a fresh, development-environment
report. V6 evidence remains historical. No live Discord messages, secret
writes, production changes, service restarts, production migrations, or deploys
were performed.

## Decision

**Production NO-GO.** Software implementation is 24/24 under the established
rubric (11 mappings + 7 source adapters + 5 legacy publishers + central
router). The complete backend test suite and 98% coverage gate pass. Production
acceptance remains blocked by channel identity/credential configuration,
seven source keys, host Docker/provenance access, full disposable stack and
rollback qualification, live canary authorization, and deployment approval.

## Source inventory and publisher migration

| Source family | Adapter / ownership | Event coverage | V7 evidence | Runtime status |
|---|---|---|---|---|
| GitHub release, issue, milestone, feature | Control Center GitHub workflow and community adapter | release, milestone, confirmed/resolved issue, approved feature | GitHub adapter tests; workflow YAML parsed | Implemented and mock-tested; repository secret not inspected/configured |
| RAG | `omnibioai-rag/ragbio/notifications/discord_events.py` | sanitized incident/recovery and approved docs events | RAG Discord tests, 10/10 | Client tests pass; production signing key absent |
| Workbench | `omnibioai-workbench/notifications/discord_events.py` and publisher CLI | sanitized public incident/recovery and approved release | Workbench tests, 14/14 | Client tests pass; production signing key absent |
| Documentation | shared signed Control Center publisher CLI / docs publication workflow | documentation publication | shared client signing/route tests | Workflow/secret not live-verified |
| Video | `omnibioai-videos/scripts/publish_discord_video_event.py` | approved published video | Videos tests, 6/6 | Client tests pass; production signing key absent |
| Infrastructure/security | Control Center legacy `notify()` central path and signed CLI | infrastructure alert, sanitized security alert | Central-alert and router tests | Code path verified with mock; production endpoint/key absent |
| Support | `scripts/publish_support_discord_event.py` | approved public incident/resolution | support publisher tests | Static sanitized client tests pass; no external support system/secret verified |

All seven source identities and their allowed event families are present in
the central source contract. Source authentication is HMAC over timestamp,
nonce, and exact request bytes; the event store rejects replayed nonces,
source/event mismatches, wrong routes, malformed schemas, and unapproved
payload assertions. The source client contract tests enumerate all seven
identities and allowed source/event destinations. This is software and mocked
runtime evidence, not proof that production credentials exist or that upstream
GitHub/deployment workflows have run.

| Legacy publisher | V7 migration result |
|---|---|
| RAG direct publisher | Central signed event client; sanitized public event templates; focused tests pass |
| Workbench direct publisher | Central signed event client; user/workflow notices are not public; 14 tests pass |
| Documentation shell publisher | Central signed client; stable publication identity; auth/error tests pass |
| Ecosystem build shell publisher | Central CLI path; legacy fallback only if central configuration absent |
| Control Center alert `notify()` | Migrated to signed central unapproved alert when central URL/key exist; direct webhook fallback retained only when central configuration is absent; permanent central rejection never falls back |

The last migration carries stable event IDs. Known-issue records missing old
IDs use a deterministic title/opened-at digest. Tests prove central submission,
fixed sanitized content, signing headers, 429/5xx/network retry behavior,
permanent rejection without direct fallback, and old direct-webhook
compatibility. Runtime equivalence and production cutover are not verified.

## Event and channel matrices

All 11 event mappings are defined and tested:

| Event types | Destination |
|---|---|
| `platform.release`, `platform.milestone` | announcements |
| `github.issue.confirmed`, `github.issue.resolved` | bug-reports |
| `feature.request.accepted` | feature-requests |
| `support.incident`, `support.resolved` | support |
| `documentation.published`, `video.published` | tutorials |
| `infrastructure.alert`, `security.alert` | omnibioai-alerts |

| Channel | Policy | Secret presence | Identity verified |
|---|---|---:|---:|
| announcements | Automated | Missing | No |
| bug-reports | Automated | Missing | No |
| feature-requests | Automated | Missing | No |
| support | Automated | Missing | No |
| tutorials | Automated | Missing | No |
| omnibioai-alerts | Automated | Legacy alert variable present | No |
| general | Community-only | Not applicable | Community channel identity not inspected |
| research-chat | Community-only | Not applicable | Community channel identity not inspected |
| show-and-tell | Community-only | Not applicable | Community channel identity not inspected |

The active Studio `.env` was inspected using a presence-only check: the
nonempty relevant key was `DISCORD_ALERT_WEBHOOK_URL`. There was no
`DISCORD_CHANNEL_WEBHOOKS` and no source signing key in that file. Process
environment contained no Discord keys. No secret value was printed. Thus
`CHANNELS_CONFIGURED=1/6` refers only to legacy alert-variable presence;
`VERIFIED_CHANNEL_MAPPINGS=0/6`. All three community channels are absent from
automated routing and were excluded by the disposable route test (3/3).

Operator provisioning manifest (values must be created in the authorized
secret manager, not copied into source control):

1. Create one distinct incoming webhook in the intended server/channel for
   each automated channel; store them as keys `announcements`, `bug-reports`,
   `feature-requests`, `support`, `tutorials`, and `omnibioai-alerts` inside
   `DISCORD_CHANNEL_WEBHOOKS`.
2. Verify each webhook's server/channel identity and send permission using
   Discord-admin-authorized inspection. Do not infer identity from URL shape.
3. Preserve `DISCORD_ALERT_WEBHOOK_URL` until the alerts replacement is
   canary-verified; do not map one webhook to multiple channels.
4. Create seven independent high-entropy keys in the existing secret manager:
   `DISCORD_EVENT_GITHUB_SECRET`, `DISCORD_EVENT_RAG_SECRET`,
   `DISCORD_EVENT_WORKBENCH_SECRET`, `DISCORD_EVENT_DOCUMENTATION_SECRET`,
   `DISCORD_EVENT_VIDEO_SECRET`, `DISCORD_EVENT_INFRASTRUCTURE_SECRET`, and
   `DISCORD_EVENT_SUPPORT_SECRET`. Inject each producer's own key only and
   retain previous-key overlap only during controlled rotation.

Verified source credentials: **0/7**. Secret-manager write access was not
available; no keys were generated or installed.

## Security and reliability

IAM/security qualification passed at the isolated Control Center FastAPI
routing stack using synthetic JWT identities and temporary SQLite state.
Tests cover missing/invalid/expired/revoked tokens, permission/tenant denial,
source HMAC mismatch and replay, source isolation, forged approval, invalid
routes, approval/replay/queue authorization, conflict paths, and authorized
approval. These tests do not verify integration with production IAM or token
revocation infrastructure.

The full suite covers routing, schema validation, secret redaction, mention
suppression, payload limits, retry, rate limits, permanent 4xx, 5xx ambiguity,
DLQ behavior, stable IDs, deduplication, concurrent claims, and migration
compatibility. Three subprocess tests cover crash before persistence, after a
durable claim but before HTTP, and after mocked remote acceptance. Restart
delivers the unpersisted event and preserves both persisted ambiguous outcomes
without blind resend. The remaining requested process-level fault matrix
(including crash during submission, worker-pool restart, database interruption,
and configuration reload) has **not** been executed; report
`CRASH_RECOVERY=NOT_VERIFIED`, not PASS.

The in-process disposable flow passed all six automated channel routes through
signature, schema, approval, persistence, routing, mocked Discord delivery,
receipt and duplicate suppression; it verified 3/3 community exclusions.
This is not a disposable multi-container/service stack. Docker-backed E2E and
isolated rollback remain blocked by Docker socket denial. Ambiguous delivery
remains operator-reconciliation-only; no exactly-once external delivery
claim is made.

## Fresh test evidence

| Suite | Outcome |
|---|---:|
| Full Control Center backend, configured coverage command | 2,224 passed; 0 failed; 599 warnings; 72 subtests passed |
| Backend statement coverage | 8,947 / 9,129 = 98.01%; existing `fail_under=98` passed |
| Focused Control Center Discord/API/source cases | 91 passed (run independently; overlaps full suite) |
| RAG Discord tests (`--no-cov`) | 10 passed |
| Workbench Discord tests (`--no-cov`) | 14 passed |
| Videos publication tests (`--no-cov`) | 6 passed |
| Disposable six-route in-process mock | PASS: 6/6 routes; 3/3 community exclusions |
| Discord GitHub workflow YAML parsing | PASS; no `actionlint` binary was available |
| Process-level crash/restart tests | 3 passed; persisted ambiguous states not resent |

Environment: isolated `/tmp/omnibioai-control-center-system-312`, Python
3.12.3. Coverage threshold and measurement scope were not changed. The full
backend command completed in 28.77 seconds. Warnings include existing JWT key
length and framework deprecations; they did not fail tests. RAG's repository
default coverage command measures all RAG modules and therefore is not used
for this targeted test; `--no-cov` was used only to run its Discord-specific
test file. No test was skipped to produce the Control Center green result.

## Deployment, live canary, and rollback

Read-only host inspection reported `aarch64`, Docker context `default`, and
permission denied connecting to `/var/run/docker.sock`. No permission change
or escalation was attempted. `aws` CLI/secret-manager client was not present.
The repository deployment inventory contains a Control Center service/image
name, but this does not establish the running image, digest, source commit,
architecture, secret injection, or persisted storage. Therefore:

- ARM64 image qualification: **NOT_QUALIFIED**.
- Source-to-image provenance: **NOT_VERIFIED**.
- Active deployment configuration: **NOT_VERIFIED**.
- Docker disposable stack: **BLOCKED**.
- Isolated rollback: **NOT_VERIFIED**.
- Live canaries: **0/6; BLOCKED** (no explicit operator authorization,
  verified channel mapping, or readback access).
- Production deployment: **not performed; separate approval absent**.
- Production unchanged: **YES**.

## Source commit inventory

These are local repository HEAD identifiers at qualification time, not a
claim that uncommitted changes are included in those commits:

| Repository | HEAD |
|---|---|
| Control Center | `f37ce8c` |
| Workbench | `79feb3da` |
| RAG | `9e7f6b6` |
| Videos | `7120631` |
| Docs | `559ed48` |
| Studio | `ec0772e7` |

## Release gates

| Gate | Status | Evidence / remaining condition |
|---|---|---|
| G1 central router | PASS | Full backend suite and isolated routing/E2E tests |
| G2 11 event mappings | PASS | All mapping routes covered by central route tests |
| G3 six configured and verified channels | BLOCKED | Legacy alert key present; 0/6 identities verified |
| G4 seven connected/authenticated sources | BLOCKED | 7/7 code contracts and mocked tests; production source keys absent |
| G5 five legacy publishers migrated/retired | PASS | Fifth Control Center path now centrally routes when configured; mock/failure/fallback tests pass |
| G6 IAM/security | PASS | Real FastAPI route stack with isolated signed test identities and negative authorization tests |
| G7 reliability/crash recovery | NOT_VERIFIED | Full fault matrix not process-qualified |
| G8 backend regression and 98% coverage | PASS | 2,222 pass; 98.01% statements |
| G9 ARM64 provenance/deployment config | BLOCKED | Docker daemon permission denied; active deployment not inspectable |
| G10 six authorized live canaries | BLOCKED | 0/6; no explicit live-publish approval or verified hooks |
| G11 isolated rollback | BLOCKED | Docker-backed disposable stack unavailable |
| G12 production deployment approval | BLOCKED | Explicit approval not provided; no deployment attempted |

**Release gates passed: 5/12 = 41.7%. Production decision: NO-GO.**

## Changed in V7 and next operator actions

V7 code changes: central legacy-alert forwarding and retry/sanitization tests;
stable fallback event IDs for pre-ID known-issue records; expanded Discord
retry/claim/configuration tests; real route approval/conflict coverage; and
storage snapshot trust-boundary tests needed to reach the unchanged backend
coverage threshold. The runbook now records V7 status and exact provisioning
requirements.

Operator sequence to close production gates:

1. Discord/server administrator: provision six distinct channel webhooks and
   authorize read-only destination verification.
2. Secret-manager operator: store the six-channel map plus seven independent
   source keys; provide only source-scoped keys to producers.
3. Deployment operator: provide authorized read-only DGX Docker access and
   secret-manager references; verify immutable ARM64 digest, provenance,
   compose, persistence, and health, then run isolated E2E and rollback.
4. Discord publisher/operator: explicitly approve six synthetic test
   messages, then verify each actual channel and deduplication.
5. Release owner: separately approve production deployment after all other
   gates pass. No deployment is authorized by this report.
