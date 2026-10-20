# Approval replay and isolated recovery qualification

Environment: disposable MySQL 8.0.46 container, bound to `127.0.0.1:33316`; synthetic users, roles, credentials, and Ed25519 keypair only. The test-only Auth snapshot was `/tmp/omnibioai-auth-recovery-implementation-v1`; its test fixture was minimally adapted to accept MySQL URLs. The live/staging Auth and database containers were not used. The disposable database container was stopped and removed after the run.

Command executed the focused suite `tests/test_admin_credential_recovery.py` in the cached Auth Python 3.11 image with staged pytest 8.3.5/fakeredis 2.31.0 dependencies. Result: **14 passed, 7 warnings, 11.27s**.

Coverage observed in the suite:

- API-level generic JSON 401 for a disabled verifier; no account enumeration or `UnknownHashError` leakage; oversized password handling.
- Existing `bcrypt` and `bcrypt_sha256` login compatibility.
- Valid signed recovery; new password login; old password rejection; stable ID, email, active state, and roles preserved; session and refresh revocation; structured audit event without secret values.
- Invalid signature, expired approval, wrong target ID/email, wrong typed confirmation, already-enabled verifier, invalid/inactive approver, and weak candidate password rejected without credential mutation.
- Audit exception causes rollback of verifier and session changes.
- MFA remains enforced when reset scope is absent; reset requires explicit signed Platform Owner scope and is audited.
- Approval replay denied on a fresh DB session after successful use.
- Concurrent attempts with distinct valid approvals for the same disabled target commit at most once; exactly one completion event exists.
- No password argument or public recovery route.

Replay persistence after a process restart was not tested by forcibly restarting MySQL. The committed, uniquely keyed `RevokedToken` claim is database-backed and therefore restart-persistent by design; this remains a code/schema inference, not a crash-restart test result. Similarly, no dedicated multi-process race was run; the unique DB constraint is the cross-process serialization guard, while the test uses concurrent workers and sessions.

Critical unqualified item: recovery revokes refresh tokens and session rows but not outstanding access-token JTIs. Immediate access JWT revocation is a P0 blocker, notwithstanding the passed tests.
