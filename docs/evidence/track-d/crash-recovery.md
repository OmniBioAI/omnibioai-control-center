# Track D — crash-recovery qualification

Date: 2026-10-25

Scope: Docker-free qualification of the synchronous Discord event router and
publisher. No Docker resource, production service, credential, webhook, or
database was accessed or changed.

## Result

The authoritative scenario IDs DCR-01 through DCR-18 are preserved. Fourteen
scenarios are applicable to this synchronous SQLite/HTTP implementation and
have deterministic local evidence. Four historical worker/queue/hot-reload
scenarios are inapplicable as worded and are not counted as passes or silently
remapped. Docker-backed full-service restart tests remain pending Track A's
authorized qualification environment.

Track D's original focused run:

```text
PYTHONPATH=backend/src /tmp/omnibioai-control-center-py312/bin/python -m pytest -q -o addopts='' backend/tests/test_discord_process_crash.py backend/tests/test_discord_events.py backend/tests/test_discord_event_client.py backend/tests/test_discord_routing.py backend/tests/test_discord_iam_api.py
```

Original result: `109 passed, 59 warnings in 3.67s`.

Post-integration focused rerun (includes the Track E retry-boundary and
defensive-validation tests):

```text
PYTHONPATH=backend/src /tmp/omnibioai-control-center-system-312/bin/python -m pytest -q -o addopts='' backend/tests/test_discord.py backend/tests/test_discord_events.py backend/tests/test_discord_routing.py backend/tests/test_discord_event_client.py backend/tests/test_discord_iam_api.py backend/tests/test_github_discord_event_adapter.py backend/tests/test_support_discord_publisher.py backend/tests/test_discord_process_crash.py
```

Integrated focused result: `138 passed, 1 warning in 3.30s`.

The fault injection is deterministic and local: injected HTTP transports and
sleep functions model 429, 4xx, 5xx, connect failure, and read timeout;
exclusive SQLite locks model persistence failure; explicit child exit codes
73–76 model process death at fixed delivery boundaries; a filesystem barrier
coordinates concurrent claimants. Temporary directories isolate all state.

## Historical scenario dispositions

| ID | Historical scenario | Disposition | Fresh Docker-free evidence |
|---|---|---|---|
| DCR-01 | Crash before persistence | Applicable; an unpersisted request cannot be acknowledged | `test_api_crash_before_event_persistence_is_unacknowledged_and_retryable` sends a valid signed API request, terminates before event commit, proves no response was returned and no event was persisted, then accepts a fresh-nonce retry after restart |
| DCR-02 | Crash after persistence | Applicable; committed event rows survive store reconstruction | `test_durable_ingest_dedup_conflict_approval_and_receipt` |
| DCR-03 | Crash before HTTP submission | Applicable; a durable publisher claim becomes ambiguous rather than being resent | `test_process_dies_after_durable_claim_before_http_restart_preserves_ambiguity` |
| DCR-04 | Crash during submission | Applicable; an in-flight send is never blindly resent | `test_process_dies_during_submission_then_restart_does_not_resend` |
| DCR-05 | Remote acceptance before local receipt | Applicable; external outcome is ambiguous absent a local receipt | `test_process_dies_after_mock_acceptance_and_restart_never_blindly_resends` uses a deterministic local HTTP receiver ledger: receiver records acceptance, withholds the response, the publisher process is terminated, then restart must remain ambiguous and not resend; plus `test_local_2xx_receipt_recovers_crash_before_event_receipt_write` |
| DCR-06 | Restart with pending records | Applicable; pending approval/queued state survives store reconstruction | `test_durable_ingest_dedup_conflict_approval_and_receipt` |
| DCR-07 | Restart with ambiguous records | Applicable; stale claims become `delivery_unknown` and are not resent | `test_stale_pending_send_after_restart_becomes_ambiguous_not_resent` |
| DCR-08 | Concurrent worker claims | Inapplicable as worded: there is no worker queue. The synchronous claim exclusion analog is separately covered, not substituted as this historical scenario | `test_concurrent_processes_cannot_claim_the_same_event` (analog only) |
| DCR-09 | Duplicate event submission | Applicable; stable event IDs suppress duplicates and reject conflicting content | `test_durable_ingest_dedup_conflict_approval_and_receipt` |
| DCR-10 | Discord 429 | Applicable; bounded `Retry-After` behavior uses injected responses and sleep | `test_rate_limit_honors_retry_after_and_then_succeeds` |
| DCR-11 | Discord 5xx | Applicable; first 5xx is classified ambiguous without blind retry | `test_5xx_is_ambiguous_and_not_blindly_retried` |
| DCR-12 | Network interruption | Applicable; connect failures retry, post-connect timeouts become ambiguous | `test_read_timeout_is_ambiguous_but_connect_error_can_retry` |
| DCR-13 | Database interruption | Applicable; exclusive SQLite lock fails closed before submission | `test_database_lock_failure_never_submits_to_discord` |
| DCR-14 | Dead-letter transition | Applicable to the publisher's metadata-only JSONL dead-letter contract, not a queue DLQ | `test_missing_or_revoked_webhook_permission_dead_letters_without_retry` |
| DCR-15 | Authorized replay | Applicable; failed/unknown delivery requires explicit manage-infra replay/reconciliation | `test_failed_delivery_can_only_be_replayed_explicitly` plus the replay IAM cases in `test_discord_iam_api.py` |
| DCR-16 | Worker restart during retry | Inapplicable as worded: no worker exists. The publisher-process interruption analog is separately covered, not substituted | `test_publisher_process_restart_during_retry_preserves_ambiguous_claim` (analog only; prior test name said “worker” but did not exercise a worker) |
| DCR-17 | Configuration reload | Inapplicable: the implementation has process-start environment loading, not a supported hot-reload contract | Configuration is re-read only when a publisher/store is constructed |
| DCR-18 | Queue reconciliation after process termination | Inapplicable as worded: there is no queue. Stale SQLite reconciliation is separately covered, not substituted | `test_crash_during_http_is_ambiguous_and_requires_operator_reconciliation` (analog only) |

Docker-free status: applicable scenarios **14/14** exercised; historical IDs
reviewed **18/18**. Full Docker-backed service crash qualification remains
pending and this report does not claim it passed.

## V10-D fresh verification

Run date: 2026-10-25. This current-tree rerun supersedes the prior focused
counts above for acceptance while preserving them as historical evidence.

Integrated Discord/IAM/recovery command:

```text
PYTHONPATH=backend/src /tmp/omnibioai-control-center-system-312/bin/python -m pytest -q -o addopts='' backend/tests/test_discord.py backend/tests/test_discord_events.py backend/tests/test_discord_routing.py backend/tests/test_discord_event_client.py backend/tests/test_discord_iam_api.py backend/tests/test_github_discord_event_adapter.py backend/tests/test_support_discord_publisher.py backend/tests/test_discord_process_crash.py
```

Result: **138 passed, 1 warning in 3.69s**. The existing harness ownership
suite also passed **32 tests and 6 subtests**. Full backend regression
collected **2,239 tests: 2,239 passed**, with **98.01%** statement coverage
against the configured 98% minimum (`31.98s`, 601 warnings). An initial
sandboxed run was blocked by socket-creation restrictions; the final run used
a socket-capable execution context and is the accepted current-tree result.

The integrated test run executes the Docker-free evidence named in each
applicable row above. Its deterministic setup is isolated temporary SQLite,
injected HTTP results/sleep, process exits at explicit boundaries, and an
interprocess barrier for concurrency. Expected outcomes are recorded in each
row; temporary directories/processes are cleaned by pytest fixtures and child
termination. The named test functions and this result record are the evidence
artifacts. The 4 inapplicable worker/queue/hot-reload dispositions remain
unchanged.

The Docker harness safety suite is not Docker-backed recovery evidence. Agent
A's corrected harness is ready for an authorized operator, but current Docker
daemon state cannot be inspected here. The latest retained run failed before
the test runner and is not promoted as a pass. See
[`release-acceptance-v10-d.md`](release-acceptance-v10-d.md) for the single
12-gate matrix and precise remaining blockers.
