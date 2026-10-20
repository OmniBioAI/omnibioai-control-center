# Admin credential recovery runbook

## Gate: do not execute against the DGX account yet

The inspected Auth service has no supported password recovery command or endpoint. The only current password-creation route creates a new user; the Admin MFA reset route requires an already-authenticated platform administrator. A direct database update is prohibited. This runbook becomes executable only after the designed Auth recovery service and local operator command have been implemented, reviewed, and passed the isolated test suite in `ADMIN_CREDENTIAL_RECOVERY_TESTS.md`.

This document does not authorize a live reset. Live recovery was not performed.

## Approval and identity verification

1. Open an incident/change ticket and record the reason for recovery.
2. Verify the requester through the established out-of-band administrator identity process. Require a second authorized approver. Record both operator and approver identities in the ticket and audit context.
3. Independently verify the intended existing row is user ID `1`, email `admin@omnibioai`, status `active`, role `admin`. Stop if any value differs. Do not alter email, roles, account status, or create another account.
4. Confirm that this is the DGX local Auth service and the designated local Auth database. Record the service/image version and database target without recording secret environment values.
5. Obtain a protected database backup or snapshot using the site's standard procedure. Verify the backup completed and can be restored to an isolated location. Do not copy the backup to an unprotected path.

## Authorized recovery mechanism

After implementation approval, run the Auth local operator command from the Auth service's supported runtime and approved operator account. Supply only the exact user ID, current email, and ticket reference as non-secret arguments. The command must require exact interactive confirmation, read the new password twice with terminal echo disabled, apply Auth's password policy and `bcrypt_sha256` hasher, revoke existing sessions, and write a signed audit event in one transaction. Never put the password in command arguments, shell history, environment variables, files, clipboard capture, support tickets, logs, or this report.

If existing MFA is enabled and the Admin cannot use its enrolled factor, stop until the second approver explicitly approves MFA reset. The implemented operator command must call the existing MFA reset service and record its audit event as part of the recovery transaction. If no MFA reset path is available in the reviewed command, do not improvise with database edits or disable MFA by another route.

## Expected audit records

- `password_recovered`, with actor/operator and approver references, target ID, ticket, recovery channel, and non-secret counts/flags only.
- One `session_revoked` event per revoked session with reason `credential_recovery`.
- `mfa_reset_by_admin` only when explicitly approved and performed.
- Subsequent `login_success` and MFA enrollment/challenge events during verification.

Audit records must not contain a password, password verifier, bearer/refresh/challenge token, TOTP secret, or plaintext recovery code.

## Post-recovery verification

1. Confirm the command reports success and the audit ledger contains the expected events. Confirm ID, email, active status, and Admin role are unchanged.
2. From the local Admin Console, log in using the newly selected password. Verify invalid-password behavior separately only in an isolated test environment; do not repeatedly probe the live account and trigger throttling.
3. Complete the MFA challenge if enabled. If recovery reset MFA, enroll a new TOTP device, verify it, generate recovery codes once, and store them in the approved secret manager. Do not place codes in the ticket or report.
4. Verify a prior refresh session is rejected. Access tokens may remain valid until their configured expiry (default 15 minutes) where no per-user access-token revocation exists; keep the recovery window controlled for at least that interval.
5. Verify the Admin Console reaches its authorized landing page and that no privilege, email, or identity fields changed.

## Failure and rollback

If policy validation fails, choose a different password interactively and retry only within the approved recovery session. If audit writing, session revocation, MFA reset, database commit, or verification fails, stop and preserve logs without secret values. The recovery service must roll back all writes on transaction failure. Do not restore a database snapshot over the live database as an ad hoc rollback; involve the database operator, assess whether the recovery transaction committed, and restore only under the site's approved recovery procedure. If login remains unavailable after a committed recovery, preserve the same identity and escalate to Auth service support rather than creating another Admin or editing credential fields directly.

## Completion record

Record ticket ID, operator/approver, Auth version, target ID, timestamps, event IDs, session-revocation count, MFA action, login verification result, and any residual access-token expiry window. Do not include the selected password, its verifier, tokens, MFA secret, or recovery codes. Keep the current email `admin@omnibioai`; any future email change is a separate authorized identity-management operation.
