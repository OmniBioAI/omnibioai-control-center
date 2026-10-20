# Auth administrator recovery test results

## Isolated environment

Tests ran against a disposable copy of the Auth repository under `/tmp/omnibioai-auth-recovery-implementation-v1`, in a Docker container with `--network none`. Pytest and fakeredis were staged separately under `/tmp`; the application test fixture used throwaway SQLite and faked Redis/HIBP. No live database, running Auth service, credential, or external auth endpoint was used.

## Focused results

- Final recovery/login API suite: **14 passed**. It covers disabled-verifier JSON 401 behavior, oversized input, bcrypt/bcrypt_sha256 compatibility, signed approvals, target/confirmation checks, enabled-credential rejection, password policy, identity/role preservation, refresh/session revocation, audit output and rollback, MFA challenge preservation/completion, explicit owner-authorized MFA reset, single-use approval, concurrent distinct approvals, no password CLI option, and absence of a public recovery route.
- Broader related suite: **253 passed, 2 skipped** across recovery, Auth login, password policy, security, session, MFA, and audit tests.
- Full Auth suite on the disposable copy: **1,572 passed, 52 failed, 35 skipped**. The focused recovery and all touched-path suites passed. The full-run failures were in existing unrelated dirty-checkout/bootstrap, rate-limit/MFA-throttle test environment, migration, and permission-registry groups. A representative migration failure is the pre-existing local `0032_manual_license_security` migration issuing `ALTER TABLE ... DROP NOT NULL`, which SQLite rejects; representative bootstrap/permission failures involve existing local edits outside this change. The Auth checkout was already dirty before this work and those changes were preserved.

## Full-suite failure classification

- Login/MFA throttle failures ran with the cached image's Redis 8.1.0 and the temporary fakeredis 2.31.0 test dependency. These tests did not pass in this isolated environment; the recovery suite itself does not change rate-limit code.
- SQLite migration failures point to the existing local manual-license migration and its SQLite-incompatible `ALTER COLUMN` operation. This work adds no migration.
- Bootstrap and permission-registry failures occur in pre-existing locally modified Auth files, not files changed by this workstream.

## Live-operation boundary

No live recovery was run. No Admin password, MFA state, email, identity, role, license, or production database was changed. There was no deployment.
