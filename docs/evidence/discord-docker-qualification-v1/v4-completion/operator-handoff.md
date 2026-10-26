# V4 operator handoff

## Immediate authorized-terminal action

Use the Docker access commands in `docker-access-report.md` from the already authorized DGX operator shell. Do not use sudo, alter socket permissions/groups, switch daemon endpoints, or bypass sandbox controls. If `docker info` fails there, stop and resolve access through the platform owner.

Before the next harness run, independently review a focused diagnostics addition to the existing `scripts/discord-docker-qualification/run_qualification.py`: preserve redacted Redis service exit/health/oom data and bounded Redis-only logs before cleanup. Preserve the current immutable-ID ownership checks, manifest, guaranteed after-inventory, and cleanup behavior. Never store `.Config.Env` or synthetic signing/webhook values.

Then run exactly:

```bash
python3 scripts/discord-docker-qualification/run_qualification.py
```

Review the new run's before/after inventories and ownership report. Only diagnose or clean resources listed in that run's ownership manifest. Do not use `docker compose down`, global prune, or project-prefix matching. If Redis starts and the router becomes healthy, the harness may proceed into the existing Docker E2E; collect the route, community exclusion, and negative-security evidence. Stop after any ownership, inventory, or cleanup failure.

## Remaining non-Docker work / external owners

- Independent reviewer: accept the 18 scenario applicability dispositions; ensure no queue/worker tests are silently substituted in this synchronous implementation.
- Release engineering: identify a real compatible previous Discord candidate and schema/config contract before rollback rehearsal.
- Discord administrator: verify/create six distinct channel webhooks and guild/channel identities; no live canary until separately authorized.
- Secret manager/runtime owners: provision and qualify seven distinct source credentials through approved interfaces; no values in evidence.
- Regression owner: provide a permitted backend test environment for the 13 loopback/socket failures and reach at least 98% current-candidate coverage.
- Integration owner: review legacy publisher migration and operational metrics/runbook against supported synchronous behavior.
- Release owner: separately authorize live canaries and production deployment only after technical gates close. Production deployment is not authorized by this handoff.
