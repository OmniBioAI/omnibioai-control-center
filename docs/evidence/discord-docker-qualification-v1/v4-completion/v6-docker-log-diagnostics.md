# V6 Docker CLI log diagnostics

Workstream: `OMNIBIOAI_DISCORD_DOCKER_LOG_DIAGNOSTICS_V6`  
Repository HEAD at implementation: `f37ce8c952f917f607e9923cbb47dda8b0406a7a`

## Implementation

The direct read of `/var/lib/docker/containers/.../*-json.log` has been removed. The existing `DockerCLI.container_log_streams` adapter now invokes `docker logs --timestamps --tail 200 <full immutable container ID>`, with a 30-second timeout. Both Docker CLI output streams are bounded to 64 KiB at retrieval and 16 KiB per persisted field. Docker CLI routes the container's stdout/stderr streams to its corresponding output pipes. Redaction occurs before evidence persistence.

The existing finalization `finally` path now attempts diagnostics independently for `redis`, `mock-discord`, and `state-init`, writing `redis-diagnostics.json`, `mock-discord-diagnostics.json`, and `state-init-diagnostics.json`. Each service must be unique and allowlisted; all run-labeled containers are checked for full IDs, exact project and workstream/run/disposable labels, and known service names. The requested service is additionally checked against its manifest-expected name and then re-inspected by immutable ID before state or logs are read. A verified ID is added to and persisted in the existing run ownership manifest. Unknown, ambiguous, missing, or mismatched resources are reported and never logged.

State inspection uses a Go template selecting only status, exit code, health status, OOM-killed flag, error, and created/started/finished timestamps. Container config/environment is not inspected: `DockerCLI.resource_by_id` now uses a selective container inspect template for labels and identity only. Logs use Docker CLI, not direct filesystem or socket access.

The existing cleanup and after-inventory finalizer remains in place and is called regardless of per-service diagnostic errors. Diagnostic errors are separately recorded in `ownership-verification.json` and redacted. No Docker containers were started during V6.

## Verification

- Python syntax checks: PASS.
- Existing ownership plus new log diagnostic tests: **28/28 PASS** using a fake Docker adapter.
- Compose config validation: PASS; command only rendered configuration and did not start containers.
- `git diff --check`: PASS.
- Independent safety review: **PASS**, performed by a separate reviewer after review of the exact V6 diff. The reviewer confirmed direct Docker log-file access is absent; exact ID/ownership validation and selective inspect are enforced; no `.Config.Env` is requested; all three services are covered; output limits/redaction and finally/cleanup/after-inventory ordering are correct. The reviewer also reran py_compile and all 28 tests. No Docker command was invoked.

## Prior authorized-run context

The latest retained pre-V6 evidence is run `20261025T064429Z-9fbc7a63`. Its Redis diagnostics failed specifically while directly opening `/var/lib/docker/containers/<id>/<id>-json.log` with `PermissionError`; this established a diagnostics access failure, not a Redis root cause. Its ownership report records cleanup and protected comparison PASS with 178 container fingerprints before and after. The operator also reported mock-discord startup failure in that run. V6 adds mock-discord and state-init capture so an authorized rerun can preserve their state and logs. The old run is preserved unchanged as historical evidence.

Tests cover success, missing service, discovery/immutable-ID ownership mismatch, ambiguity, unknown service, Docker log retrieval failure, oversized outputs, secret redaction, cleanup/after-inventory following diagnostics failure, and use of the exact immutable ID in the `docker logs` command. Docker runtime behavior remains untested; this change does not establish Redis root cause or fix startup.

No production services, credentials, Discord messages, Docker permissions, or Docker resources were changed.

Ready for execution only by the already authorized DGX Docker operator. Existing command from repository root: `python3 scripts/discord-docker-qualification/run_qualification.py`. This authorization is limited to operator execution; this V6 implementation did not run Docker.
