# Auth Admin recovery P0 acceptance

Workstream: `OMNIBIOAI_AUTH_RECOVERY_IMPLEMENTATION_RECONCILIATION_P0`

- Canonical recovery implementation: signed local CLI + transactional service is the best-supported implementation, but is not accepted for live recovery until the access-JWT gap is closed.
- Competing implementation: `scripts/recover_local_password.py` remains present and unmodified; its sudo-only authorization, email targeting, and missing replay guard make it non-canonical.
- Disabled-verifier HTTP behavior: qualified as generic JSON 401 in isolated MySQL test run.
- Approval checks: expiry, Ed25519 signature, active Platform Owner role, operator binding, stable target binding and disabled state are implemented. One-time claim is transactionally persisted and uniquely constrained.
- Replay/concurrency: focused MySQL qualification passed 14 tests, including replay and concurrent recovery; process-restart durability is inferred from the committed MySQL row and was not crash-tested.
- MFA: preserved unless a distinct signed approval explicitly permits reset; existing MFA challenge path is not bypassed.
- Access JWT revocation: **FAIL / P0 BLOCKER**. Session and refresh revocation do not immediately invalidate already-issued access JWTs.
- Full-suite baseline: clean HEAD ran in the same cached image/dependency setup: 22 failed, 1,568 passed, 9 skipped. It reproduced baseline rate-limit/throttling and bootstrap failures. Prior dirty source had 52 failures; dirty-only migration/permission/bootstrap errors are non-HEAD local changes but cannot be precisely attributed among all other edits. No recovery regression is established.
- Live state: no live service, identity, credential, database, or production configuration was changed; no live recovery, deployment, or license issuance was performed.

Acceptance status: **PARTIAL / BLOCKED for live recovery**. The isolated recovery path is qualified for the behaviors listed above, but the workstream cannot claim P0 readiness while access JWTs survive recovery and baseline triage is incomplete.
