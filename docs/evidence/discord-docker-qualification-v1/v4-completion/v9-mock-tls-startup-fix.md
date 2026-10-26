# V9 disposable mock Discord TLS startup correction

Workstream: `OMNIBIOAI_DISCORD_MOCK_TLS_STARTUP_FIX_V9`

## Confirmed failure

Authorized DGX run `20261025T065800Z-1e46fe03` recorded mock-discord exit code 1 at `SSLContext.load_cert_chain()` with `PermissionError`. The run's Redis was running but only `health=starting`; it is not a Redis readiness pass. `state-init` exited 0. Diagnostics, cleanup, isolation, and 178/178 protected container fingerprints were reported PASS/unchanged.

The harness's qualification Dockerfile ends with `USER 10001:10001`; mock-discord inherits that non-root identity (Compose does not override it). Before V9, OpenSSL created `server-key.pem` owned by the DGX operator with mode 0600, and `tls/` was 0755. The key's owner UID did not match container UID 10001, so the receiver could traverse the directory but could not read the private key. This was not a certificate-file or directory traversal failure.

## Correction

The disposable `state-init` service receives exactly one writable TLS bind mount: the run-scoped `server-key.pem` file, mounted at `/run/server-key.pem`. Its command changes ownership of that file and the disposable state directory to `10001:10001`, using its already-existing `CHOWN` capability. The TLS directory itself is not mounted into `state-init`. The key remains mode 0400. Its parent TLS directory is mode 0711 (traversal without listing or write); the enclosing run directory remains mode 0700. The temporary CA signing key and CSR/extension/serial artifacts are deleted after issuance; only `ca.pem`, `server.pem`, and `server-key.pem` remain. Public certificates are mode 0444.

Mock-discord now waits for `state-init` to complete successfully before starting. It receives the TLS directory read-only. Router and test-runner continue to receive only the CA certificate, not the server private key. No receiver runs as root, no key is world-readable, no production path or permissions are changed, and no TLS material is mounted into unrelated containers. State-init's `mkdir -p`, directory mode, and ownership operations are idempotent. It remains bounded, read-only-root, no-new-privileges, and has only its existing `CHOWN` capability.

The current mount contract is asserted by the Docker-free test: `state-init` has one read-write bind mount from `${RUN_DIR:?run directory required}/tls/server-key.pem` to `/run/server-key.pem`; the receiver remains non-root at image UID/GID `10001:10001` and receives read-only certificate material. The test checks the literal ownership target and evaluates the key and directory permission bits without attempting privileged `chown`.

## Verification

- TLS generation permissions, parent traversal mode, removal of CA signing material, and Python `SSLContext.load_cert_chain()` fixture: PASS.
- Receiver identity, literal state-init ownership target, restricted file-only writable mount, and service ordering: PASS.
- All Docker-free harness tests: **31/31 PASS**.
- Python syntax: PASS.
- `docker compose config --format json`: PASS (render-only); `validate_rendered_config`: PASS.
- `git diff --check`: PASS.
- No Docker daemon command or container startup was performed in V9.
- Redis and mock-discord runtime health remain **UNVERIFIED**; Docker E2E is 0/6.
- The safety properties were reviewed in a separate review pass, but a reviewer separate from the implementer was unavailable in this execution context. Requested independent safety review is therefore **NOT OBTAINED**; do not proceed with operator runtime execution until a separate reviewer approves the change.
- Production services, production Compose, credentials, Discord messages, and protected Docker resources were not touched by this implementation.

## V11 safety-review closure

V11 pins and validates the numeric TLS owner as UID:GID `10001:10001`; the
receiver remains UID:GID `10001:10001`, and the single writable TLS bind mount
to `state-init` remains the `server-key.pem` file. Docker-free tests reject a
wrong UID and a wrong GID independently. The key is mode `0400` before the
container's `CHOWN` capability transfers it to the receiver identity.

Certificate generation removes the temporary CA key, CSR, extension and
serial files from a `finally` path. Tests inject errors during CA key creation,
server-key generation, extension writing, certificate signing and permission
hardening, plus interruption. The original exception object remains the
primary exception with sensitive printable output scrubbed. Cleanup failures
are recorded as a safe exception note without replacing that primary failure;
after otherwise successful generation, cleanup failure is raised. Current
test counts, checksum verification and the fresh independent V11 review are
recorded in `docs/evidence/discord-v11/`.

## Operator next step

After independent review, run the existing harness from the repository root in the authorized DGX terminal:

```bash
python3 scripts/discord-docker-qualification/run_qualification.py
```

Require Redis `health=healthy`, mock-discord `health=healthy`, state-init exit code 0, clean diagnostics/cleanup/after-inventory, and unchanged protected-resource fingerprints before treating startup as qualified. This run must preserve mock diagnostics if ownership initialization or TLS loading still fails.
