# OmniBioAI Discord V5 qualification

Date: 2026-10-24  
Workstream: `OMNIBIOAI_DISCORD_100_PERCENT_PRODUCTION_READINESS_V5`  
Decision: **NO-GO for production**  
Production changes: none; live Discord messages: none.

This report is fresh V5 evidence. V4 material is historical and is not counted
as a V5 test run. No credential values, message payloads containing private
data, or webhook URLs are included.

## Source revisions inspected

| Repository | Revision inspected | V5 working-tree changes in scope |
|---|---|---|
| Control Center | `f37ce8c` | GitHub issue/milestone/release adapter + workflow; focused tests; runbook/evidence |
| RAG | `9e7f6b6` | No V5 edits; signed sanitized publisher retained |
| Workbench | `79feb3da` | No V5 edits; publisher client retained, no trusted event caller found |
| Documentation | `559ed48` | No V5 edits; central publish behavior retained |
| Studio | `ec0772e7` | No V5 edits; presence-only `.env` inspection |
| Videos | `7120631` | Public video publication notifier, tests, and CI integration |
| Ecosystem utilities | `637201c` | No V5 edits; signed build-alert publisher retained |

Revisions identify inspected repository baselines, not deployed image provenance.
Repositories had pre-existing V4 working-tree modifications; only the V5 files
listed below are attributed to this workstream.

## Source matrix

The seven-source contract is unchanged: `github`, `rag`, `workbench`,
`documentation`, `video`, `infrastructure`, `support`.

| Source | V5 event coverage / source path | Authentication and approval | Status |
|---|---|---|---|
| GitHub | Release, closed milestone, maintainer-labeled confirmed/resolved issue, maintainer-labeled accepted feature. New adapter reads GitHub event file and emits stable object-ID events. | Independent HMAC source key contract; signed central submission; always unapproved. Private repo, PR, draft/prerelease, unreviewed event, and user text excluded. | Implemented in code; key absent; workflow parsed and unit-tested, not run in GitHub Actions. |
| RAG | Existing sanitized support/documentation events. | HMAC central client; no research/query/user/data payload; key absent. | Connected code path; runtime auth not verified. |
| Workbench | Signed event client and Celery task exist. No trusted approved operational caller located. | HMAC client contract; no key. | Not connected to an actual event producer. |
| Documentation | Existing docs deploy publication event. | HMAC central client; publication event pending central approval; key absent. | Connected code path; runtime auth not verified. |
| Video | New workflow detects newly public video manifest records with approved SHA-256/size and stable hash-derived event ID. Generic safe content only. | HMAC central submission; `approved_publication=false`; key absent. | Implemented and unit-tested; actual hosted workflow not run. |
| Infrastructure | Existing ecosystem build-failure central alert publisher. | HMAC source contract; legacy alerts fallback preserved; key absent. | Limited connected code path. General deployment/recovery and sanitized security feed absent. |
| Support | No trusted incident/ticket producer or public-redaction approval system found. | Contract exists; no credential or producer. | Not connected. |

Connected source code: **5/7** (GitHub, RAG, documentation, video, limited
infrastructure). Runtime source credentials configured: **0/7**. Workbench and
support are not counted as connected sources.

## Channel configuration

All nine names are explicitly recognized in the router. Six are automated;
three remain community-only. Presence was checked without displaying values in
the local Studio `.env`; the legacy alert variable exists. No production
secret-manager or Discord read access was available.

| Channel | Automation | Secret/config status | Identity/readback |
|---|---|---|---|
| `announcements` | platform release/milestone | Missing | Not verified |
| `bug-reports` | confirmed/resolved issue | Missing | Not verified |
| `feature-requests` | accepted feature | Missing | Not verified |
| `support` | public incident/resolution | Missing | Not verified |
| `tutorials` | docs/video publication | Missing | Not verified |
| `omnibioai-alerts` | infrastructure/security alert | Legacy alert key present only; new map entry absent | Not verified |
| `general` | Community only | No automated route | Protected by fixed route allowlist |
| `research-chat` | Community only | No automated route | Protected by fixed route allowlist |
| `show-and-tell` | Community only | No automated route | Protected by fixed route allowlist |

Configured-key count is **1/6** (presence only); verified channel mappings are
**0/6**. Never infer a channel from a webhook's variable name. Operator
provisioning is six distinct webhook values under `DISCORD_CHANNEL_WEBHOOKS`
for the six automated channels, preserving the legacy alert fallback until
the `omnibioai-alerts` destination is independently verified.

## Legacy publisher migration

| Historical path | V5 state | Duplicate/rollback note |
|---|---|---|
| RAG direct notifications | Central signed event client | No production key; do not run old and new delivery together |
| Workbench user notification | Kept non-public; signed public-event client exists | No trusted public event caller found; user/workflow details must stay private |
| Documentation deploy | Central signed event client | No production key; rollback retains legacy behavior only where explicitly configured |
| Ecosystem shell build alert | Central CLI publisher with failure propagation | Existing alert fallback preserved; no silent success on non-2xx |
| Control Center alert publisher | Existing compatibility path retained | Not retired; replacement route/channel is not verified, so change risks alert loss |

Migrated or safely retired: **4/5**. The fifth remains active for compatibility
until a separately authorized destination canary proves replacement delivery.

## Tests and static checks

Fresh V5 focused commands and results:

| Area | Executed | Result |
|---|---:|---|
| Control Center Discord routing/events/client/GitHub adapter | 57 | PASS, 57 passed |
| RAG async Discord publisher | 10 | PASS, 10 passed |
| Workbench Discord publisher | 8 | PASS, 8 passed (Django plugin disabled only for this isolated module; host test environment supplies dotenv) |
| Video publication adapter | 6 | PASS, 6 passed |
| Focused total | 81 | **81 passed, 0 assertion failures** |
| Supplemental IAM dependency + router reliability subset | 53 | PASS, 53 passed (overlaps the Control Center focused total; direct dependency tests are not HTTP-stack IAM qualification) |
| Disposable in-process signature→durable approval→mock Discord→dedupe | 1 flow | PASS; not an API/IAM/container stack |
| GitHub release/community + video workflow YAML | 3 workflows | PASS parsing; no hosted workflow execution |
| Python compilation / shell syntax | Relevant publisher scripts and two legacy shell publishers | PASS |

Focused channel tests exercise all 11 mappings, each of the six automated
destinations, and rejection/configuration behavior for the three community
channels. The disposable script covers one synthetic `announcements` flow; it
does not claim six-channel delivery or production IAM.

The full backend environment now has the declared sentry/SQLAlchemy/WeasyPrint
dependencies and collects **2,152 tests**. Full regression execution was
attempted in the provisioned Python 3.12 and Python 3.14 environments but did
not complete: FastAPI `TestClient` dispatch stalls at the first
`test_analytics_router.py::AuthenticationTestCase::test_invalid_token_returns_401`
request and hits the bounded timeout. This is not counted as a pass or an
assertion failure. The full-suite denominator remains 2,152 collected; the
number completed before the stall is not used as a pass rate.

## Reliability and security qualification

Existing router tests freshly pass retry/rate-limit, bounded delivery, route
isolation, dedupe, persistence, DLQ, mention suppression, payload schema,
secret redaction, and ambiguous delivery behavior. The system does not promise
exactly-once Discord delivery: if Discord may have accepted a webhook but a
receipt was not durably saved, state becomes ambiguous and automatic retry is
stopped; an authorized operator must reconcile visibility before replay.

Cryptographic signature comparison, timestamp/nonce replay checks, per-source
key separation, server-side approval policy, and IAM dependency unit behavior
have focused test coverage. However, V5 could not execute real Discord route
dispatch with the production IAM identity/revocation service. IAM/tenant
isolation is therefore **NOT VERIFIED** at runtime. No public event is approved
by a source payload alone; new GitHub/video publishers explicitly submit
unapproved events.

Crash recovery, six-channel disposable service stack, authorized DLQ replay
through live IAM, and configuration reload under running workers were not
qualified as a complete integration environment. Existing unit/fault-injection
coverage is scoped and does not replace those gates.

## Deployment, live delivery, rollback

The local host reports `aarch64`; Docker daemon inspection returns permission
denied on the Docker socket. AWS CLI/secret-manager access is unavailable. No
DGX image digest, SBOM/provenance-to-source relationship, active production
configuration, migration compatibility, network, persistent queue mount, or
production health/restart behavior was verified. No permission changes or
privilege escalation were attempted.

Live Discord canaries: **0/6**. No operator approval, six verified webhook
destinations, or authorized readback capability was available. No messages
were sent. Isolated Docker rollback: **NOT VERIFIED** because Docker daemon
access is unavailable. Production rollback/deployment was not attempted.

## Release gates

| Gate | Result | Evidence / blocker |
|---|---|---|
| G1 Central router | PASS | 57 focused tests; disposable in-process flow |
| G2 11 mappings | PASS | Fresh exact-route tests; community channels excluded |
| G3 Six configured/verified automated channels | BLOCKED | 1 legacy key only; 0/6 destinations independently verified |
| G4 Seven authenticated event sources | BLOCKED | 5/7 code paths; 0/7 credentials; Workbench caller and support source absent |
| G5 Five legacy publisher migrations | BLOCKED | 4/5; preserve Control Center alert path pending verified replacement |
| G6 IAM/security | BLOCKED | HMAC/payload security unit tests pass; API IAM/revocation runtime not verified |
| G7 Reliability/crash recovery | BLOCKED | Focused retry/dedupe/DLQ and crash-ambiguity unit tests pass; complete restart/fault matrix and disposable service stack not run |
| G8 Complete backend regression | BLOCKED | 2,152 collected; TestClient dispatch hangs under available host runtime |
| G9 ARM64 image/provenance/config | BLOCKED | Host architecture known; Docker/socket and secret manager unavailable |
| G10 Six live canaries | BLOCKED | No live publication authorization; 0/6 sent |
| G11 Disposable rollback | NOT_VERIFIED | No disposable Docker host access |
| G12 Production approval | BLOCKED | Explicit deployment authorization absent; no deployment attempted |

Passed release gates: **2/12 = 16.7%**. Production readiness: **NO**.

Percentages use fixed, explicit denominators:

- Overall release-gate completion: 2 passed / 12 = **16.7%**.
- Software implementation: (11 mappings + 5 connected source adapters + 4
  migrated/retired legacy paths + 1 router) / (11 + 7 + 5 + 1) = **21/24 =
  87.5%**. This is code implementation only, not credentials or runtime
  qualification.
- Automated channel secret presence: 1/6 = **16.7%**; independently verified
  destination mapping: 0/6 = **0%**.
- Trusted source integration: 5/7 = **71.4%** code paths; production source
  credentials: 0/7 = **0%**.
- Focused tests: 81 passed / 81 executed = **100%**; complete backend suite is
  separately blocked, so this is not an overall regression rate.
- Live acceptance: 0/6 = **0%**.

## V5 changes and exact operator actions

V5 adds the GitHub issue/milestone workflow and adapter, moves release event
metadata parsing out of shell interpolation, fails closed for private repos,
pull requests, drafts and prereleases, and adds a video-publication adapter and
CI integration. It adds eight GitHub-adapter tests and six video tests (fresh
counted suites above). It refreshes the runbook and qualification evidence.
The existing alerts publisher and production configuration were not changed.

Required operator actions, in order:

1. Provision six channel-specific webhooks in the authorized Discord server and
   store the six-map JSON as `DISCORD_CHANNEL_WEBHOOKS`. Preserve the current
   alert fallback; separately confirm its actual channel identity.
2. Provision seven independent URL-safe 32-byte-or-stronger HMAC secrets using
   the authorized secret manager, one each for `github`, `rag`, `workbench`,
   `documentation`, `video`, `infrastructure`, and `support`; configure only
   each source's key plus the verifier key. Do not share values across sources.
3. Connect and approve a Workbench operations producer and a support incident
   producer; decide whether broader deployment/recovery/security feeds are
   required and connect only sanitized trusted sources.
4. Run the complete backend regression in an approved environment where
   `TestClient` works; exercise IAM-protected queue/approve/replay routes against
   test IAM and verify tenant/revocation behavior.
5. With authorized DGX read-only access, verify ARM64 immutable image digest,
   source provenance, configuration/secrets references, persistent notification
   storage, migrations, and restart/health behavior; run the disposable six-
   channel end-to-end and rollback stack.
6. Obtain explicit approval for six labeled synthetic live canaries, then
   verify each actual channel by authorized readback. Production deployment
   requires a separate explicit authorization and remains unapproved.

## V5 changed-file manifest

- `.github/workflows/discord-github-community-events.yml` (new)
- `.github/workflows/discord-release-event.yml` (safe event-file parsing)
- `backend/tests/test_github_discord_event_adapter.py` (new)
- `docs/discord-multichannel-integration-v1.md` (V5 addendum)
- `docs/evidence/discord-v5/qualification.md` (new)
- `docs/evidence/discord-v5/SHA256SUMS` (new)
- `scripts/publish_github_community_event.py` (new)
- `omnibioai-videos/.github/workflows/ci.yml` (video publisher integration)
- `omnibioai-videos/scripts/publish_discord_video_event.py` (new)
- `omnibioai-videos/tests/test_discord_publication.py` (new)

The SHA-256 manifest next to this report covers this sanitized report only.
