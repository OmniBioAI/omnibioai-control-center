# Admin credential recovery tests

## Validation performed

The Auth source was copied to `/tmp/omnibioai-auth-recovery-20261017`; only this disposable copy received the proposed `UnknownHashError` catch. Tests ran in a Docker container with `--network none`, mounting only that copy. Synthetic values were used.

| Check | Result |
|---|---|
| Disabled synthetic verifier returns a controlled `False` result | PASS |
| Disabled verifier takes the dummy-hash path; oversized input remains a controlled failure | PASS |
| Synthetic password verifies against a newly generated supported hash | PASS |
| Incorrect synthetic password is rejected | PASS |
| Live service, database, or identity changed | NO |

The local Auth image does not include `pytest`, and the host Python does not have Passlib installed. Consequently this was a focused verifier-level check, not an HTTP integration test. No full recovery workflow exists to test yet.

## Required isolated regression suite

Run these tests only after implementing the Auth recovery service/command. Use a disposable SQLite database and a synthetic Admin identity, a test audit key, fake Redis/throttle services, and a mocked compromised-password provider. Do not point the suite at the DGX Auth database. Do not print test passwords, hashes, cookies, or tokens.

| Scenario | Required assertion |
|---|---|
| Disabled verifier login | `POST /auth/login` returns JSON 401 with the same generic body and `Content-Type: application/json` as another invalid credential; no `UnknownHashError`, no 500, no token, no account status change. Failure audit and throttle path are exercised. |
| Unknown account vs disabled verifier | Public response shape/status are identical; disabled verifier executes dummy verification to keep the timing defense. |
| Authorized recovery | Operator/authorized route supplies the synthetic target identity and ticket; supported password hash is stored by the service, session rows are revoked, and signed recovery audit event is committed. |
| New password login | Synthetic new password authenticates; token/MFA behavior follows the account's configured MFA state. |
| Wrong password | Rejected with the generic JSON 401 response. |
| Identity/role preservation | Synthetic ID, email, active status, and role set before/after match exactly; no new user row is created. |
| Policy | Too short, too long, email-matching, locally common, and mocked compromised passwords are rejected; unavailable HIBP behavior follows configured fail-open/fail-closed policy. Rejection leaves DB/audit mutation absent. |
| MFA enrollment/challenge | Enroll TOTP, verify enrollment, log in to receive challenge, reject bad code, accept a valid code, and issue session only after challenge completion. |
| MFA reset | Without explicit approval state remains unchanged; with explicit authorized recovery, existing devices/codes are invalidated, reset is audited, and fresh enrollment is required. |
| Session revocation | Prior refresh/session records cannot be used after recovery; revocation events carry the fixed recovery reason. Account access tokens remain subject to the documented expiry limit unless user-level invalidation is implemented. |
| Unauthorized recovery | Missing authentication, insufficient permission, wrong ticket confirmation, wrong target email/ID, inactive target, and non-admin target are denied without mutation. Caller cannot change roles or email through this path. |
| Audit | Successful recovery, session revocations, and any MFA reset are auditable. Passwords, verifier strings, TOTP secrets, recovery codes, and tokens are absent from audit metadata and logs. Audit failure rolls back the complete mutation. |

## Current test status

The disabled-verifier helper behavior is validated in isolation. HTTP contract assertions and all recovery, authorization, MFA, session, and audit scenarios remain unrun because the recovery implementation is absent. The installed Auth image lacks the test runner, so a future run should use the Auth repository's approved development/test environment or a test image with the pinned dependencies; it must remain isolated from live services.
