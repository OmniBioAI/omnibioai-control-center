# Track A — V10 independent safety review

Workstream: `OMNIBIOAI_DISCORD_DOCKER_E2E_V10_A`

Date: 2026-10-25

Result: **PASS for source-level safety; Docker runtime remains unverified.**

The reviewer did not edit the candidate and did not invoke Docker.

## Findings

- The reported `SSLContext.load_cert_chain()` failure is precisely explained by
  the host-operator-owned, owner-only private key and the receiver's different
  effective identity, `10001:10001`. The certificate and mounted-directory
  traversal permissions were not the failure.
- The correction is least privilege: root `state-init` drops all capabilities
  and adds only `CHOWN`; its writable TLS exposure is the single run-scoped
  `server-key.pem` bind. It changes ownership to `10001:10001` without widening
  mode `0400`, is idempotent, and must succeed before non-root `mock-discord`
  starts. The receiver sees the TLS directory read-only.
- The host run directory remains `0700`; the TLS directory remains non-listable
  and traverse-only at `0711`; public certificates are `0444`; CA signing and
  issuance artifacts are removed. No production path is changed.
- Redis explicitly uses `999:1000`, a UID/GID-matched mode-0700 `/data` tmpfs,
  a read-only root filesystem, no added capabilities, and the bounded
  `redis-cli ping` readiness contract.
- The mock readiness probe validates HTTPS against the disposable CA and the
  certificate's loopback IP SAN, connects to `127.0.0.1`, and requires the
  expected 200 response body. It is independent of Docker DNS.
- All services remain on the internal-only disposable network, expose no host
  ports, and retain CPU, memory, PID, rootfs, capability, no-new-privileges,
  and bounded-log controls.
- Immutable-ID ownership checks, two-phase cleanup prevalidation, bounded and
  redacted diagnostics, cleanup on failure, and independently attempted
  after-inventory remain intact.

## Independent verification

```text
python3 -m unittest discover -s scripts/discord-docker-qualification -p 'test_*.py' -v
Result: PASS, 32 passed, 0 failed

python3 -m py_compile scripts/discord-docker-qualification/*.py
Result: PASS

git diff --check -- scripts/discord-docker-qualification docs/evidence/track-a
Result: PASS
```

The regression suite asserts generated key/certificate modes, certificate
loading, DNS and IP SANs, exact single-key initializer mounting, configured and
resulting UID/GID, repeated initialization, preserved key mode, symlink path
rejection, Redis identity/health configuration, immutable-ID diagnostics,
redaction/bounds, interrupted and failed cleanup, and after-inventory behavior.

This review authorizes only handoff to the already authorized DGX operator. It
does not claim Redis or mock health, any of the six automated routes, any of the
three community exclusions, cleanup, or protected-container preservation for a
new runtime. Those remain unverified until the isolated harness is run.
