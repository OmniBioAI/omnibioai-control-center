# OmniBioAI Discord V6 qualification

Date: 2026-10-24  
Workstream: `OMNIBIOAI_DISCORD_FINAL_ENGINEERING_AND_PRODUCTION_QUALIFICATION_V6`  
Decision: **NO-GO for production**. Software integration advanced, but credentials,
verified channel identities, deployment provenance, live acceptance, and explicit
deployment authorization remain unavailable.

## Baseline and evidence scope

V5 evidence and its checksum were verified before work began. V5 findings are
historical, not treated as V6 qualification. At V6 start the workspace had
uncommitted V5 implementation changes; their baseline commits were:

| Repository | HEAD at V6 start |
|---|---|
| Control Center | `f37ce8c` |
| RAG | `9e7f6b6` |
| Workbench | `79feb3da` |
| Documentation | `559ed48` |
| Studio | `ec0772e7` |
| Videos | `7120631` |
| Ecosystem utilities | `637201c` |

No production service, secret, database, container, or deployment was modified.
No live Discord messages were sent.

## Source integration matrix

The existing seven-source identity contract is preserved. V6 supplies safe code
paths for all seven, but credential configuration and deployed connectivity are
not claimed.

| Source | Event coverage | V6 code path and evidence | Runtime credential |
|---|---|---|---|
| `github` | Release, milestone, confirmed/resolved issue, accepted feature | Existing signed publisher and workflows; full backend tests; YAML parsed | Missing |
| `rag` | Sanitized incident/recovery and approved docs event | Existing signed client; Discord tests 10/10 | Missing |
| `workbench` | Release, public incident, recovery | Fixed-template signed client, Celery task and operator CLI; no freeform payload/approval; tests 14/14 | Missing |
| `documentation` | Publication and approved infrastructure event | Existing central publisher/workflow; source path retained | Missing |
| `video` | Public tutorial/video publication | Existing publication client/workflow; tests 6/6; YAML parsed | Missing |
| `infrastructure` | Sanitized alert/security event | Existing signed central publisher; route and event tests | Missing |
| `support` | Public incident, recovery, service notice | New fixed-template, operator-attested CLI; event remains unapproved pending central IAM approval; tests included in backend suite | Missing |

No authoritative support ticketing service was found. The new support command is
an operator-driven event source, not a claim that a ticketing system is
connected. It does not accept ticket text or identifiers and cannot set the
approval flag. Source code paths implemented: **7/7**. Source credentials
configured in inspected local configuration: **0/7**.

## Channel configuration matrix

The active local `omnibioai-studio/.env` was inspected for names/presence only;
secret values were not printed or copied into evidence. `DISCORD_ALERT_WEBHOOK_URL`
is present, `DISCORD_CHANNEL_WEBHOOKS` is absent, and no per-source HMAC key is
present in the checked local env. No authorized secret-manager write or
Discord-admin verification was available.

| Channel | Automation | Config presence | Destination identity verified |
|---|---:|---:|---:|
| `announcements` | Yes | Missing | No |
| `bug-reports` | Yes | Missing | No |
| `feature-requests` | Yes | Missing | No |
| `support` | Yes | Missing | No |
| `tutorials` | Yes | Missing | No |
| `omnibioai-alerts` | Yes, legacy fallback present | Present only | No |
| `general` | No | Community-only | Not applicable |
| `research-chat` | No | Community-only | Not applicable |
| `show-and-tell` | No | Community-only | Not applicable |

Configured entries by presence: **1/6**; independently verified channel
mappings: **0/6**; community exclusions: **3/3**. The legacy alerts value is
not proof of its destination identity. Do not reuse it for another channel.

## Legacy publishers

| Publisher path | Status |
|---|---|
| RAG direct notifications | Migrated to central signed event client (V5 baseline) |
| Workbench user/pipeline notification | Safely non-public; fixed-template operational event source added |
| Documentation deploy notices | Migrated to central signed event client (V5 baseline) |
| Ecosystem shell build alert | Central CLI path with nonzero failure propagation (V5 baseline) |
| Control Center `notify()` alerts | Still direct compatibility path; not changed because replacement destination/credentials cannot be verified |

Migrated or safely retired: **4/5**. The last path remains intentionally
operational until central alert delivery is proven; no duplicate path was
introduced.

## Fresh test results

| Suite | Result |
|---|---:|
| Complete Control Center backend assertions (`--no-cov`) | **2,158 passed**, 0 failed/errors; 72 subtests passed |
| Control Center configured coverage run | All 2,158 tests passed; pytest exits nonzero because coverage is **96.59%**, below configured **98%** gate |
| Control Center Discord focused routing/client/event suite | **59/59 passed** |
| Control Center API IAM + SQLite subprocess crash tests | **6/6 passed** |
| Workbench publisher and CLI tests | **14/14 passed** |
| RAG Discord tests | **10/10 passed** |
| Video publication tests | **6/6 passed** |
| Six-route in-process mock event pipeline | **PASS**; 6 automated routes, 3 community exclusions, approval, mock delivery, and dedupe |
| Python compilation | PASS |
| Relevant workflow YAML parse | PASS (Control Center release/community, video CI) |
| Legacy shell syntax | PASS (`bash -n` docs deployment and ecosystem builder) |

The complete backend suite was run in isolated Python 3.12 under `/tmp`; the
declared `pandas` dependency was installed in that environment only. Existing
TCP/HTTP checks required authorized localhost socket access. The TestClient
stall was reproduced in a minimal FastAPI application and fixed in test setup
by selecting uvloop on supported Linux hosts; application lifespan and thread
offloading were not disabled. The ordinary coverage gate remains a failure;
its threshold was not reduced. The separate no-coverage execution proves all
test assertions completed, but does not turn the configured coverage gate
green.

The process-crash test starts a child worker using actual SQLite persistence,
terminates it at a mocked remote-acceptance boundary, then restarts and verifies
the durable pending claim is converted to `unknown` without a second send. The
broader required fault matrix (database interruption, all crash points,
configuration reload, full service restart and queue behavior) is not fully
qualified; do not infer complete crash recovery from this test.

## Deployment, live, and rollback evidence

Host reports `aarch64`, but Docker daemon access is denied at
`/var/run/docker.sock`; Docker context is `default`. No image digest, image
architecture, build provenance, source-to-image mapping, deployment secrets
reference, production DB compatibility, or health/restart state was verified.
AWS CLI/secret-manager write access was unavailable. Thus ARM64 image
qualification and deployment configuration are **not verified**.

The in-process mock flow is not a disposable backend/IAM/database/worker service
stack. Docker denial prevents the requested isolated stack and rollback test.
No live canary was sent: no operator publication authorization, verified
channel configuration, or readback credentials were available. Live canaries
are **0/6**. Rollback is **not verified**. Production deployment approval was
not provided.

## Twelve release gates

| Gate | Status | Evidence / blocker |
|---|---|---|
| G1 Central router | PASS | Existing durable central router plus fresh backend tests |
| G2 11 event mappings | PASS | Mapping table and route tests cover all 11 |
| G3 Six verified destinations | BLOCKED | 1/6 config presence; 0/6 channel identities verified |
| G4 Seven authenticated sources | BLOCKED | 7/7 code paths; 0/7 source secrets configured |
| G5 Five legacy publisher paths | BLOCKED | 4/5; legacy Control Center alerts remains active |
| G6 IAM/security tests | PASS | Real FastAPI router with signed test tokens, source HMAC, authz negatives, approval and replay checks |
| G7 Reliability/crash recovery | NOT_VERIFIED | Unit fault coverage and subprocess crash case pass; full matrix/service recovery incomplete |
| G8 Full backend regression | FAIL | 2,158 assertions pass; configured coverage 96.59% < 98% |
| G9 ARM64 provenance/config | BLOCKED | Docker host permission denied; no immutable image provenance |
| G10 Six live canaries | BLOCKED | 0/6; authorization/config/readback absent |
| G11 Isolated rollback | BLOCKED | Disposable service stack unavailable |
| G12 Production approval | BLOCKED | Separate explicit approval absent |

Passed gates: **3/12 = 25%**. Software implementation: **23/24 = 95.8%**
under the explicit rubric `11 mappings + 7 source code paths + 5 legacy paths
+ central router`. This software score does not include credentials or runtime
qualification. Verified channel configuration is **0/6**; source integration
code is **7/7**; backend assertions execute/pass **2,158/2,158 = 100%**, but
the configured regression command fails its coverage gate. Live delivery
acceptance is **0/6 = 0%**. Production readiness: **NO-GO**.

## Operator actions to close

1. Provision six distinct channel webhooks via Discord administration and the
   authorized secret manager; set `DISCORD_CHANNEL_WEBHOOKS` and verify each
   webhook against its actual server/channel. Preserve
   `DISCORD_ALERT_WEBHOOK_URL` until alerts replacement is verified.
2. Generate/store seven independent high-entropy source keys via the
   authorized secret manager for the exact `DISCORD_EVENT_<SOURCE>_SECRET`
   contract listed in the runbook. Validate key/source isolation and rotation
   without displaying values.
3. Prove central alert-path equivalence, then migrate or formally retire the
   existing direct Control Center alerts publisher; keep compatibility until
   then.
4. Raise measured coverage to the existing 98% threshold through valid test
   coverage (do not lower the threshold) and rerun the normal backend command.
5. Obtain authorized read-only DGX Docker access for immutable ARM64 image and
   source provenance checks; run disposable service E2E and isolated rollback.
6. Obtain explicit authorization for six synthetic live canaries, verify each
   destination with permitted read access, then obtain separate production
   deployment approval. No deployment is authorized by this evidence.
