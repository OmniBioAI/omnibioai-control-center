# Admin credential recovery runbook

## Readiness gate

This runbook is for a future operator-approved local recovery. It does not authorize a live recovery and no live recovery was executed. Before use, verify that the reviewed Auth source containing `app.cli.recover_admin` is in the approved local runtime, its test suite passed in the intended deployment environment, the Ed25519 public key is mounted read-only at the fixed path, and the external Platform Owner approval system is available. Do not run against a production database or as part of deployment.

## Approval and identity verification

1. Open an incident/change ticket for the local DGX Admin recovery.
2. Verify the administrator's identity through the organization's established out-of-band process. Record the verification reference without recording secret answers or identity documents in the Auth database.
3. Require an active Platform Owner (global `platform_admin` plus `admin`) to approve the exact target user ID, current email `admin@omnibioai`, expected disabled/unsupported verifier state, named local operator login, ticket, and expiry. If MFA reset may be needed, make that a separate explicit signed approval scope. The Platform Owner's private signing key must remain outside the DGX and Auth runtime.
4. Verify the target in a read-only review: user ID `1`, current email `admin@omnibioai`, status `active`, global role `admin`. Stop if any value differs. Do not edit email, role, status, or create another user.
5. Record the Auth image/source version and confirm the selected database is the intended local Auth database without printing DB credentials or secret environment values.

## Backup and invocation

1. Take and verify a protected backup/snapshot of the local Auth database using the site's standard process. Confirm a restore can be performed to an isolated location. Do not make an ad hoc copy in an unprotected directory.
2. Use the approved named operator login in the controlled Auth runtime with database access. The public key must be root-owned, read-only to the operator, not a symlink, and not group/world writable.
3. Place the signed, short-lived approval record in the protected approval location. The file is not a password or private key; keep its ticket/identity metadata within the approved process.
4. Invoke the local command with only the stable user ID and approval file path:

   ```text
   python -m app.cli.recover_admin --user-id 1 --approval-file /protected/approval/admin-recovery.json
   ```

5. Confirm the displayed user ID, exact current email, and ticket by typing the requested phrase. Enter the new password twice in the no-echo prompts. Use a newly generated unique password that meets Auth policy. Never use CLI arguments, shell history, environment variables, files, clipboard logging, or tickets for the password.

## Expected audit and session effects

On commit, expect one signed `credential_recovery_completed` event containing the approver/operator references, target ID, ticket, identity-verification reference, approval UUID, and session count; one `session_revoked` event per session with reason `credential_recovery`; and `mfa_reset_by_admin` only if an approved reset occurred. There will also be a namespaced single-use approval claim in `revoked_tokens`. None of these records may contain passwords, verifier strings, access/refresh/challenge tokens, TOTP secrets, or recovery codes.

Refresh tokens and persisted sessions are revoked. Existing access tokens may remain accepted until their configured expiry; default is 15 minutes. Keep the recovery window controlled for at least that period.

## Post-recovery verification

1. Confirm the command reports commit success and the audit ledger contains the expected events. Confirm user ID, email, active status, roles, and existing associations are unchanged.
2. Log in through the local Control Center using the newly chosen password. Confirm the Admin landing/deep-link route is accessible.
3. If MFA remained enabled, complete the normal MFA challenge with the enrolled factor. If the signed approval authorized MFA reset, enroll and verify a new TOTP device and generate recovery codes through the existing MFA routes; store them only in the approved secret manager. Never record codes in this runbook or ticket.
4. Verify an old refresh token/session is rejected. Do not assume an already-issued access token is immediately invalidated; observe the configured expiry window.
5. Confirm audit metadata and Auth logs contain no entered password or verifier material.

## Failure handling and rollback

Invalid signatures, expired/replayed approvals, wrong operator/target, enabled credentials, policy rejection, and unauthorized Platform Owner state must produce no committed change. If DB, session revocation, MFA reset, audit signing, or commit fails, the service rolls back all recovery writes, including the approval claim. The command prints a generic failure without SQL parameters or secret values.

If the command fails, preserve the ticket and non-secret diagnostics, confirm the approval remains usable only if no transaction committed, and involve the Auth/database operator. Do not manually edit credential fields or restore a snapshot over the live database. If a committed recovery still cannot log in, keep the same identity and escalate through the approved Auth support process; do not create a replacement Admin or disable MFA ad hoc.

## Completion record

Record ticket ID, operator and Platform Owner approver, target user ID, Auth version, timestamps, audit event IDs, number of revoked sessions, MFA action, post-login result, and any remaining access-token expiry window. Do not include the password, verifier, tokens, MFA secret, or recovery codes. Keep the email `admin@omnibioai`; any future email change is a separate approved operation.
