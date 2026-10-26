# OmniBioAI Discord final end-to-end qualification

Date: 2026-10-24  
Workstream: `OMNIBIOAI_DISCORD_FINAL_END_TO_END_PRODUCTION_CLOSURE`

## Decision

**PARTIAL; candidate UNSTABLE; production NO-GO.** The current candidate is
fingerprinted in `release-candidate-manifest.json`, but remains a set of dirty
worktrees, not an immutable build. No production service, database, credential,
or persistent storage was modified. No webhook was provisioned and no live
message was sent.

Source-level implementation remains present (24/24); all 11 event mappings
pass mocked routing tests. Four of five publisher paths are migrated or safely
retired under the conservative V2 definition; Control Center's compatibility
fallback remains. Channel configuration is 1/6 presence-only, verified channel
identity is 0/6, and source credentials/runtime configuration are 0/7. Current
Control Center backend regression passes 2,234 tests and 72 subtests at 98.00%
coverage. Cross-repository regression is blocked by unresolved dependencies,
collection errors, and absent browser binaries.

## Candidate reconciliation

V2's 112, V9's 109, and V10's 119 focused Discord passes were from distinct
worktree states and are not added to current results. V8's 2,224 backend
passes/98.01% is historical. The current candidate's full Control Center
backend run is 2,234 passed, zero failed, 72 subtests passed, 98.00% coverage.
The Docs repository was three commits behind; its three already-fetched commits
were inspected and fast-forwarded because none overlapped its two local edits.
All other changes, including unrelated Studio storage/account work, were
preserved. Auth is included in the manifest because the integration relies on
IAM contracts; its current dirty `.dockerignore` change is unrelated and was
not modified.

V2's 4/5 migration count is retained as the operational count: RAG notices are
centrally routed or retired; Workbench public notices are retired while its
signed client remains; Docs and build-shell use the central client with
controlled fallback; Control Center alerts still require destination and
replacement equivalence verification. V8's 5/5 counted code-level
central/fallback support, not production migration. No path is claimed to have
production delivery equivalence.

## Current evidence matrix

| Automated destination | Configured presence | Guild/channel/webhook association | Route evidence |
|---|---|---|---|
| announcements | Missing | Not verified | Mock route pass |
| bug-reports | Missing | Not verified | Mock route pass |
| feature-requests | Missing | Not verified | Mock route pass |
| support | Missing | Not verified | Mock route pass |
| tutorials | Missing | Not verified | Mock route pass |
| omnibioai-alerts | Legacy setting name only | Destination unknown | Mock route pass |

`CHANNELS_CONFIGURED=1/6` means presence only; `VERIFIED_CHANNEL_MAPPINGS=0/6`.
No webhook token or complete URL was read into evidence. Duplicate webhook IDs,
malformed URLs/ports, and legacy-alert aliasing are rejected in code. The
community destinations `general`, `research-chat`, and `show-and-tell` are not
automated routes.

| Source | Secret reference | Key/runtime verified |
|---|---|---|
| GitHub | `DISCORD_EVENT_GITHUB_SECRET` | No |
| RAG | `DISCORD_EVENT_RAG_SECRET` | No |
| Workbench | `DISCORD_EVENT_WORKBENCH_SECRET` | No |
| Documentation | `DISCORD_EVENT_DOCUMENTATION_SECRET` | No |
| Video | `DISCORD_EVENT_VIDEO_SECRET` | No |
| Infrastructure | `DISCORD_EVENT_INFRASTRUCTURE_SECRET` | No |
| Support | `DISCORD_EVENT_SUPPORT_SECRET` | No |

All seven source contracts exist, but actual secret-manager values, injection,
and configured runtime acceptance are 0/7. No approved secret manager or
Discord admin session was available. `DISCORD_ALERT_WEBHOOK_URL` remains a
compatibility path; its real destination is unverified and it was not removed.

## Test and reliability qualification

The supported-compatible existing Python 3.12 environment passed the complete
Control Center backend suite: **2,234 passed, 0 failed, 72 subtests passed;
98.00% coverage**. The separate Discord IAM API suite passed 15 tests. RAG's
focused Discord suite passed 10 tests in an existing environment, Videos'
focused signed-publication suite passed 6, and Workbench's focused publisher
suite passed 12 using test-only Django settings and an ephemeral test key.
Those focused cross-repository results do not establish complete repository
qualification.

RAG full-suite collection was blocked by missing dependencies (`iam_client`,
`ollama`, `python-dotenv`, and other declared modules); Videos' full suite had
312 pass, 16 skip, 2 xfail, and 39 errors because the Playwright Chromium
executable is absent; Workbench full-suite collection stopped with 351 errors,
including missing dependencies and duplicate test module names. Docs' shell
syntax passes; its Vitest suite could not be run because `node_modules` is
absent. No repo lockfiles were found for Control Center, RAG, Workbench, or
Videos.

Control Center tests cover all 11 mappings, six routes, signature/source
contracts, approval and IAM APIs, stable event IDs, duplicate suppression,
secret redaction, bounded retries, 429/Retry-After, permanent 4xx, ambiguous
5xx, dead-letter/replay paths, and channel isolation. Seven real subprocess
tests terminate workers against temporary durable SQLite, including concurrent
claims and restart around ambiguous delivery. They use mocked remote Discord
transport; they do not complete the full container/API crash matrix or prove
exactly-once delivery.

| Required process/crash case | Current evidence |
|---|---|
| Crash before persistence | Local subprocess test |
| Crash after persistence | Local durable-state/process tests |
| Crash before HTTP submission | Local claim/worker termination test |
| Crash during submission | Local process killed during mocked submission |
| Remote acceptance before local receipt | Mocked acceptance followed by process termination |
| Restart with pending records | Local SQLite restart tests |
| Restart with ambiguous records | Local test verifies no automatic retry |
| Concurrent worker claims | Two-process claim test |
| Duplicate event submission | Stable-ID idempotency unit test |
| Discord 429 | Mocked bounded Retry-After test |
| Discord 5xx | Mocked ambiguous-state test |
| Network interruption | Mocked connect/read failure tests |
| Database interruption | SQLite lock/fail-closed test |
| Dead-letter transition | Unit-level queue/DLQ tests |
| Authorized replay | Local replay path tested; IAM-protected live API replay not verified |
| Worker restart during retry | Local subprocess restart test |
| Configuration reload | Not run |
| Queue reconciliation after process termination | Unit-level reconciliation only; full service restart not run |

The matrix is therefore **partial**, not a full crash-recovery PASS.

## Infrastructure and acceptance

The observed host is `spark-c275`, Linux `aarch64`; hardware identity was not
confirmed. Docker context is `default`, but the daemon denied access in this
session. No image IDs/digests or container configuration were inspected. Static
Compose validation passed previously; it is not image provenance. The V8
runner's fresh in-process flow passed six mock routes, three community
exclusions, signature, approval, persistence, and duplicate checks. It is not
Docker E2E.

| Gate | Result | Current evidence |
|---|---|---|
| G1 Central router | PASS | Focused router suite and mock route flow |
| G2 Event mappings | PASS | 11/11 mappings under tests |
| G3 Six verified destinations | BLOCKED | 0/6 identity readbacks |
| G4 Seven authenticated runtimes | BLOCKED | 0/7 configured production credentials |
| G5 Legacy migration/compatibility | NOT_VERIFIED | Source paths audited; production equivalence absent |
| G6 IAM security | PASS | 15 current isolated Discord IAM API tests passed |
| G7 Full crash recovery | NOT_VERIFIED | Local subprocess matrix passed; full service matrix absent |
| G8 Full cross-repository regression and coverage | BLOCKED | CC backend meets 98%; other repo suites incomplete |
| G9 ARM64 image provenance/configuration | BLOCKED | No Docker/image access |
| G10 Six live canaries | BLOCKED | 0/6; no explicit publication authorization |
| G11 Disposable rollback | BLOCKED | No Docker-backed candidate/previous-image test |
| G12 Production deployment approval | BLOCKED | Not provided; no deployment attempted |

**3/12 gates pass.** Technical qualification is BLOCKED; production readiness
is NO. `LIVE_CANARIES_PASSED=0/6`, `PRODUCTION_DEPLOYED=NO`,
`PRODUCTION_UNCHANGED=YES`.

See `test-results.md` for commands and dependency outcomes and
`operator-handoff.md` for the consolidated safe execution steps.
