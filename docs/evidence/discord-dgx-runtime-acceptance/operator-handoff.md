# Operator actions required to resume runtime acceptance

Docker access itself is no longer the blocker. This session consistently
reached Docker `29.6.2` through the permitted mechanism, completed the V8
read-only inspection, and fingerprinted the existing inventory without any
mutation. No permission, group, or socket change was made.

## Current Docker boundary

The V8 script has only `inspect` and `isolated-tests`. The latter is a local
mock, not Docker E2E. No reviewed Docker E2E/crash/rollback CLI, Compose file,
pinned candidate/prior image pair, or database/schema fixture exists here. Do
not invent or run an ad hoc stack. The next runtime-owner action is to supply a
reviewed maintained harness with:

1. a unique Compose project and isolated internal network;
2. temporary volumes/database/queue only, with no existing attachment;
3. synthetic per-source keys and a mock-only Discord endpoint;
4. pinned candidate and prior immutable ARM64 image digests with source/build
   provenance;
5. commands for six-route E2E, all 18 crash cases, rollback, evidence capture,
   and deterministic cleanup.

Re-run the documented read-only inspector immediately before and after that
harness. Abort if any target cannot be positively attributed to its unique
project.

## External owners

- Discord administrator: verify/create six distinct least-privilege channel
  webhooks and record sanitized IDs/references only. Community channels remain
  excluded. No live canary without separate explicit approval.
- Secret-manager owner: provision seven distinct source HMAC keys and verify
  injection/rotation without recording values. No supported interface was
  available here, so no credential was modified.
- Regression owner: provide the permitted loopback test context and resolve
  cross-repository dependency/Playwright blockers.
- Release owner: after G1–G11 pass, separately authorize any live canary and,
  later, production deployment. Neither authorization exists now.

Evidence destination: `docs/evidence/discord-dgx-runtime-acceptance/`.
