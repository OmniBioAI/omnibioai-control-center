# Track D — V10-D release acceptance

Date: 2026-10-25

## Decision

**Production NO-GO. Release readiness: 4/12 gates (33.3%).** Historical
scenario IDs and applicability decisions are preserved in
[`crash-recovery.md`](crash-recovery.md). Fourteen applicable scenarios have
Docker-free test evidence. Docker-backed recovery remains 0/14: the current
shell cannot inspect the Docker daemon, and Agent A's latest retained run is a
historical failed run. No exactly-once delivery guarantee is asserted; the
router is synchronous and persists ambiguous outcomes for operator
reconciliation. There is no background queue or worker.

No Discord messages were sent and no deployment was attempted. Production
remains unchanged.

## Current verification

| Verification | Result | Evidence |
|---|---|---|
| Historical crash contracts | 18/18 reviewed; 14 applicable, 4 inapplicable as worded | [`crash-recovery.md`](crash-recovery.md), DCR-01 through DCR-18 |
| Applicable Docker-free recovery | 14/14 exercised | Recovery tests listed in [`crash-recovery.md`](crash-recovery.md); command/result below |
| Docker harness ownership/cleanup tests | 32 passed, 6 subtests passed | `scripts/discord-docker-qualification/test_ownership.py`; current run below |
| Docker-backed recovery | 0/14 | Agent A readiness: [`qualification-readiness.md`](../track-a/qualification-readiness.md); live Docker state inaccessible here |
| Current integrated Discord/IAM/recovery tests | 138 passed, 1 warning | `backend/tests/test_discord.py`, `test_discord_events.py`, `test_discord_routing.py`, `test_discord_event_client.py`, `test_discord_iam_api.py`, `test_github_discord_event_adapter.py`, `test_support_discord_publisher.py`, `test_discord_process_crash.py` |
| Full backend regression | 2,239 passed, 0 failed | Fresh current-tree run in socket-capable execution context; full output summary below |
| Backend statement coverage | 98.01%; configured threshold 98% met | Same full backend run; 9,163 statements, 182 missed |

Commands run from repository root, except full backend command (run from
`backend/`):

```text
PYTHONPATH=backend/src /tmp/omnibioai-control-center-system-312/bin/python -m pytest -q -o addopts='' backend/tests/test_discord.py backend/tests/test_discord_events.py backend/tests/test_discord_routing.py backend/tests/test_discord_event_client.py backend/tests/test_discord_iam_api.py backend/tests/test_github_discord_event_adapter.py backend/tests/test_support_discord_publisher.py backend/tests/test_discord_process_crash.py
138 passed, 1 warning in 3.69s

PYTHONPATH=scripts/discord-docker-qualification:backend/src /tmp/omnibioai-control-center-system-312/bin/python -m pytest -q -o addopts='' scripts/discord-docker-qualification/test_ownership.py
32 passed, 6 subtests passed in 0.19s

PYTHONPATH=src /tmp/omnibioai-control-center-system-312/bin/python -m pytest
2,239 passed, 601 warnings in 31.98s; coverage 98.01% (configured 98% met)
```

The first sandboxed full-suite attempt had 2,226 passes and 13 socket-creation
failures (`PermissionError: [Errno 1] Operation not permitted`) and 97.96%
coverage. It was rerun in a socket-capable execution context; the clean
2,239-pass, 98.01% result above supersedes both that attempt and V7's
historical 2,224-pass result for the current tree.

## Prepared Docker-backed fault qualification

The existing harness in `scripts/discord-docker-qualification/` is the sole
prepared stack. It uses a unique run/project ID, an internal network, synthetic
credentials, run/workstream/disposable labels, persistent test-only SQLite
state, exact immutable-ID ownership checks, and cleanup followed by inventory
comparison. Docker-free ownership tests cover partial startup, runner failure,
timeouts/signals, interrupted cleanup, collision/mismatch refusal, and
idempotent cleanup. They do not count as Docker execution.

The Docker scenario plan is deterministic and requires evidence for setup,
expected result, cleanup, and artifact for each applicable case:

| IDs | Deterministic fault setup | Expected result | Cleanup and evidence artifact |
|---|---|---|---|
| DCR-01–02, 06–07 | Synthetic signed event against isolated router; terminate/reconstruct router at the named SQLite boundary | Uncommitted request is not acknowledged; committed rows survive restart; pending state persists; stale sending claim becomes ambiguous and is not resent | Harness finally-path removes only manifest-owned resources and compares before/after inventory; per-run crash matrix, router diagnostics, SQLite state assertions |
| DCR-03–05 | Terminate isolated router immediately before HTTP, during delayed mock HTTP, or after mock acceptance before local receipt write | Claim is durable; interrupted/accepted-without-receipt outcome is `delivery_unknown`; no automatic resend | Same ownership-limited cleanup; per-run crash matrix plus mock receiver request ledger and router state evidence |
| DCR-08 | Not run: historical worker-claim scenario is inapplicable because no worker queue exists | No substituted worker behavior is claimed | Preserve disposition in crash matrix; no Docker pass is recorded |
| DCR-09 | Submit same stable synthetic event ID twice, then same ID with conflicting content; separately fail one channel while delivering an unrelated channel event | Duplicate is suppressed; conflicting content is rejected; one destination's failure does not block the unrelated destination | Remove isolated state volume by manifest ID; request ledger and per-route API response artifact |
| DCR-10–12 | Mock receiver returns scripted 429/Retry-After, 5xx, connect reset, and read timeout through bounded deterministic barriers; terminate the API process during a controlled 429 backoff as the API-process analog to historical DCR-16 | Bounded 429 retry honors the selected delay; 5xx and post-connect timeout become ambiguous; connect failure follows configured retry policy; interrupted retry remains durable/ambiguous and is not resent after process restart | Remove isolated stack and volume; scripted receiver log, router diagnostics, restart state assertion, and crash matrix |
| DCR-13 | Hold exclusive SQLite lock during ingest/claim | Fail closed before outbound submission | Remove isolated state volume; DB-lock test record and mock request count |
| DCR-14 | Mock permanent webhook permission failure (401/403) | Metadata-only dead-letter transition; no retry; sensitive values redacted | Remove isolated state volume; redacted dead-letter and receiver log |
| DCR-15 | Seed failed/unknown event; call IAM replay/reconcile API with synthetic authorized and unauthorized identities | Only authorized explicit replay/reconciliation mutates state; unresolved ambiguity is not auto-replayed | Remove isolated state volume; API audit/result artifact and crash matrix |
| DCR-16, 18 | Not run as worded: no worker or queue exists | No queue/worker restart or queue reconciliation guarantee is claimed | Preserve disposition; no Docker pass is recorded |
| DCR-17 | Not run: implementation has no hot-reload contract; configuration is loaded at construction/process start | No hot-reload guarantee is claimed | Preserve disposition; no Docker pass is recorded |

For every future Docker case, the per-run evidence bundle must include the
run manifest, scenario result with setup/assertions, redacted service
diagnostics, mock request ledger, cleanup report, and after-inventory. The
run must stop before startup if Agent A cannot verify daemon identity and
absence of another qualification stack. Agent A's retained run
`20261025T065800Z-1e46fe03` failed before E2E at mock-discord TLS-key access;
cleanup and protected-inventory comparison passed for that run only (178/178
fingerprints). The corrected candidate has Track A source-review approval but
has not been run against Docker. Live Docker inventory is currently
unverifiable in this shell.

## Release gate matrix

| Gate | Status | Evidence and exact remaining blocker |
|---|---|---|
| G1 Central router | PASS | 138 focused current-tree tests pass; synchronous router behavior covered |
| G2 Eleven event mappings | PASS | Existing current-tree routing tests exercise the fixed mapping set |
| G3 Six destination identities | BLOCKED | 0/6 webhook-to-guild/channel identities independently verified |
| G4 Seven source runtimes | BLOCKED | 0/7 production credentials and runtime injections independently qualified |
| G5 Legacy publisher migration/equivalence | NOT VERIFIED | Source audit and local contracts exist; production destination equivalence and all producer runtimes remain unverified |
| G6 IAM security | PASS | Current synthetic FastAPI IAM/replay/reconcile tests pass in the 138-test integrated run; production IAM integration is not implied |
| G7 Full crash recovery | BLOCKED | 14/14 Docker-free applicable cases pass; 0/14 Docker-backed; live daemon inventory inaccessible and corrected stack not executed |
| G8 Full backend regression and 98% coverage | PASS | Current full suite: 2,239/2,239 passed; 98.01% statement coverage against the unchanged 98% threshold |
| G9 ARM64 image provenance and deployment configuration | BLOCKED | Host is aarch64, but complete immutable image provenance, attestation, source binding, active runtime configuration, and secret references are not verified |
| G10 Six live canaries | BLOCKED | 0/6; requires six verified identities and explicit publication authorization; none sent |
| G11 Disposable rollback | BLOCKED | No Docker-backed candidate/previous-image and persistent-state rollback run; compatible prior Discord candidate/schema fixture absent |
| G12 Production deployment approval | BLOCKED | Explicit deployment approval absent; no deployment attempted |

Passed gates: **4/12 (33.3%)**. Production readiness is **NO**. G9 requires
complete ARM64 provenance; G11 requires disposable rollback; G3, G4, G10, and
G12 require the six verified destinations, seven source runtimes, six
authorized live canaries, and separate explicit deployment approval stated
in the release contract.

## Exact blockers and next action

1. Agent A/authorized DGX operator: confirm current daemon identity,
   aarch64 architecture, and no competing qualification project from its
   authorized shell; then execute the existing manifest-owned harness once
   and publish the complete evidence bundle. No second stack is started from
   this shell.
2. Backend regression owner: rerun the full backend suite in a socket-capable
   approved test environment, reach at least 98% coverage, and retain the
   full output artifact. Current Discord affected tests are green.
3. Discord administrator and secret owner: verify six distinct webhook
   identities and provision/qualify seven source credentials and runtimes.
4. Release owner: complete legacy publisher runtime equivalence, ARM64
   provenance, Docker crash recovery and disposable rollback; then separately
   authorize six synthetic canaries and production deployment.

Until those blockers close, the candidate remains **NO-GO**.
