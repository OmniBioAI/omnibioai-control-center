# Track A — V10 Docker qualification readiness

Workstream: `OMNIBIOAI_DISCORD_DOCKER_E2E_V10_A`

Date: 2026-10-25

Status: **READY FOR AUTHORIZED OPERATOR EXECUTION; Docker E2E remains unverified.**

## Confirmed TLS root cause

Run `20261025T065800Z-1e46fe03` executed `mock-discord` as the qualification
image's final identity, UID/GID `10001:10001`. Its bind-mounted private key was
owned by the host operator and readable only by that different owner. The TLS
directory was traversable and the public certificate was readable, so
`SSLContext.load_cert_chain()` failed specifically when it attempted to open
`server-key.pem`. This was not a malformed certificate, certificate permission,
or parent-directory traversal failure.

The disposable `state-init` service now waits ahead of `mock-discord` and changes
ownership of only the run-scoped `server-key.pem` to `10001:10001`. It receives
that one file as a writable bind, not the TLS directory. The key remains mode
`0400`; public certificates remain `0444`; `tls/` is traverse-only mode `0711`;
and the enclosing run directory remains `0700`. The receiver mounts the TLS
directory read-only and still runs non-root. The temporary CA signing key and
issuance files are deleted before startup.

## Runtime contracts retained

- Every service uses the unique internal network and publishes no host port.
- Every service has CPU, memory, PID, bounded-json-log, read-only-rootfs,
  dropped-capability, and no-new-privileges controls. `state-init` adds only
  `CHOWN`; `mock-discord` adds only `NET_BIND_SERVICE`.
- Redis explicitly runs as the pinned image's UID/GID `999:1000`, uses a
  mode-0700 UID/GID-matched `/data` tmpfs, and has no added capability. Its
  readiness contract remains `redis-cli ping` with bounded timing.
- The mock readiness probe connects to `https://127.0.0.1/__test__/health`,
  validates the disposable CA and loopback IP SAN, and requires the exact 200
  response body. It does not depend on Docker DNS.
- Diagnostics remain allowlisted, bounded, redacted, and selected by full
  immutable container ID after exact project/service/name and run/workstream
  ownership checks. Cleanup prevalidates every target and removes by immutable
  ID; after-inventory runs even after diagnostic or cleanup failures.

## Docker-free verification

From the repository root:

```text
python3 -m unittest discover -s scripts/discord-docker-qualification -p 'test_*.py' -v
Result: PASS, 32 passed, 0 failed

python3 -m py_compile scripts/discord-docker-qualification/*.py
Result: PASS

git diff --check -- scripts/discord-docker-qualification docs/evidence/track-a
Result: PASS
```

Coverage includes TLS modes and loading, exact single-key ownership mounting,
parent traversal modes, symlink/path-traversal rejection, initializer
idempotency, deterministic mock HTTPS readiness, Redis non-root and healthcheck
contracts, immutable-ID diagnostics, diagnostic redaction and bounds, cleanup
failure, interrupted cleanup, and independently guaranteed after-inventory.

## Authorized DGX operator command

Run only from the normal shell already authorized for the DGX Docker daemon. Do
not use `sudo`, change socket permissions/groups, change daemon endpoints, or
alter production infrastructure.

```bash
cd /home/manish/Desktop/omnibioai-ecosystem/omnibioai-control-center
id
stat -c 'mode=%a owner=%u:%g' /var/run/docker.sock
printf 'DOCKER_HOST=%s\n' "${DOCKER_HOST-<unset>}"
docker context show
docker info --format '{{.ID}} {{.ServerVersion}} {{.Architecture}}'
python3 scripts/discord-docker-qualification/run_qualification.py
```

Stop before the Python command if Docker access is unavailable, the context is
not the authorized target, the host is not `spark-c275`, or the daemon is not
`aarch64`. A passing run must report Redis and mock-discord healthy, deliver all
six automated routes, exclude all three community-only channels, clean all
owned disposable resources, and leave every protected container fingerprint
unchanged.

No Docker command or production mutation was performed during V10 preparation.
Accordingly: `DOCKER_E2E=0/6`, `COMMUNITY_EXCLUSIONS=0/3`, Redis health and mock
health are unverified for the corrected candidate, and cleanup/protected-state
results remain unverified for a new run. The retained 178/178 result belongs
only to the failed historical run and is not promoted to the corrected build.
