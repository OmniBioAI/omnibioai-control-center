# V8 disposable Redis startup correction

Workstream: `OMNIBIOAI_DISCORD_REDIS_STARTUP_FIX_V8`

## Confirmed Redis failure and cause

Authorized Docker run `20261025T065232Z-a12a7bec` retained Redis exit code 1, `OOMKilled=false`, and stderr `chown: .: Operation not permitted`. The same-run diagnostics identify the pinned Redis image as `redis@sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499`, resolving to the official Redis 7.4 Alpine image. Its image metadata/Dockerfile uses `/data` as `WORKDIR`, installs `docker-entrypoint.sh`, and defaults to `redis-server`. The official Alpine Dockerfile creates user `redis` UID 999 and group `redis` GID 1000. Its entrypoint, when invoked as root with `redis-server`, finds non-redis-owned files in `.` (the current working directory `/data`) and attempts `chown` before dropping privileges with `gosu`. The observed `chown: .` therefore identifies `/data` as the target. Because the disposable service drops all capabilities, that root entrypoint cannot perform the ownership repair.

The pinned image reference itself is unchanged. Compose now sets `user: "999:1000"` and `working_dir: /data`; its existing bounded `/data` tmpfs is explicitly mounted `uid=999,gid=1000,mode=0700`. This causes the official entrypoint's root-only chown branch to be skipped and gives the defined Redis account private write access to its disposable data directory. No privileged execution, host-path ownership changes, capability additions, published ports, or production Redis changes are involved. Existing read-only root filesystem, isolated internal network, CPU/memory/PID/log limits, and dropped capabilities remain.

## Separate mock-discord finding

In the same run, mock-discord exited with code 1 and stderr `PermissionError` from `SSLContext.load_cert_chain` for its mounted key. The harness generates `server-key.pem` mode 0600 as the host operator, while the mock-discord container runs as the qualification image's non-root UID 10001. The host-owned bind-mounted private key is therefore unreadable to that process. This is an independent, evidence-backed mock TLS fixture permissions issue, not a Redis cause. V8 does not change its permissions or claim mock-discord fixed; a safe key-delivery correction is needed before end-to-end stack execution can pass.

`state-init` exited 0 in that run.

## Validation and disposition

- Regression test parses the existing Compose file and asserts pinned digest, Redis UID/GID, working directory, writable bounded tmpfs ownership/mode, read-only root, no added capability, no published ports, resource limits, and internal network isolation.
- Docker-free harness tests: **29/29 PASS**.
- Python syntax checks: **PASS**.
- `docker compose config --format json`: **PASS** (render-only; no containers started).
- `git diff --check`: **PASS**.
- Fresh technical safety checklist: PASS for service-only Compose change, pinned non-root identity, private tmpfs mode, existing read-only root, internal network, bounded resources/logs, no published ports, no new capabilities, and no edits to cleanup/ownership/diagnostic code. However, a reviewer separate from the implementer was not available in this execution context; the requested independent review is therefore **NOT OBTAINED** and the final independent-review gate is FAIL pending that review.
- Redis runtime startup remains **NOT VERIFIED** until the authorized DGX operator reruns the existing harness.
- Production services and production Compose files are unchanged.

## Operator disposition

Do not treat this static correction as Redis startup PASS. After a separate safety reviewer approves this Compose diff, use the existing authorized DGX command from the repository root: `python3 scripts/discord-docker-qualification/run_qualification.py`. That run should verify Redis health and preserve the independently diagnosed mock-discord TLS-key failure evidence; V8 does not resolve that second issue.

Sources for pinned official image metadata and entrypoint contract: [Redis 7.4 Alpine image metadata](https://hub.docker.com/layers/library/redis/7.4-alpine/), [official Redis Dockerfile template](https://github.com/redis/docker-library-redis/blob/master/Dockerfile.template), [official Redis entrypoint](https://github.com/redis/docker-library-redis/blob/master/7.2/debian/docker-entrypoint.sh). The exact runtime failure evidence above remains authoritative for this run; source metadata explains the observed behavior.
