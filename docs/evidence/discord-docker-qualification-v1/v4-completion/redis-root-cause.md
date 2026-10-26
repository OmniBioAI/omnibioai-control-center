# Redis startup failure — V4 disposition

Result: `REDIS_STARTUP=BLOCKED` (root cause undetermined; no remediation claimed).

## Evidence actually retained

The V2 run summary shows `state-init` exited and Redis exited with status 1. Compose then reported dependency failure, so the router/test-runner path did not execute. The harness performed its ownership-limited cleanup; `ownership-verification.json` records no cleanup or inventory errors and an unchanged protected inventory. The retained package contains no Redis logs, container inspect/state snapshot, health output, or Docker event record. No logs were available to inspect in V4.

Current Compose facts, from source (not a runtime diagnosis): the Redis service uses the pinned reference `redis@sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499`, command `redis-server --save "" --appendonly no --maxmemory 96mb --maxmemory-policy noeviction`, `read_only: true`, a bounded `/data` tmpfs, dropped capabilities, 128 MiB memory, 0.5 CPU, and `redis-cli ping` healthcheck. Router startup depends on Redis healthy. This inventory does not establish image architecture, entrypoint behavior, mount ownership, or actual Redis error.

## Why no fix is made

The recorded exit code alone cannot distinguish command parsing, architecture/image issues, filesystem permissions, process constraints, or another startup error. Docker access is denied in the current context, and the V2 run did not preserve diagnostics before deleting its disposable container. Changing command, mount ownership, capabilities, or resource limits without observing the failure would be speculative and could weaken isolation. No Redis config change or regression test is therefore represented as completed.

## Required next diagnostic/fix loop

1. Independently review a narrowly scoped harness change that captures only service name, immutable container ID, exit code, health state, OOM flag, and bounded Redis-only log output before cleanup. Apply conservative credential redaction; never capture `.Config.Env` or router logs containing synthetic source material.
2. In the permitted authorized terminal, capture before inventory, execute one isolated run, save diagnostics, and preserve cleanup/after-inventory behavior. If logs do not identify root cause, inspect the disposable container's image architecture, effective user, mount RW/mode/source, and Docker events for that run ID only.
3. Make the smallest evidence-backed Redis correction and add a regression test for the exact observed cause.
4. Have the safety review independently reapprove the changed startup/diagnostics path; rerun startup and then E2E only after Redis health passes.

No production Redis or database was used or modified.
