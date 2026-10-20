# Admin credential recovery design

## Status

Preparation only. The existing Auth service has no password recovery API or operator recovery command. This design describes the required local Auth change; it is not an instruction to edit the live database or to perform the recovery. The existing Admin identity remains user ID `1`, email `admin@omnibioai`, role `admin`, status `active`.

## Entry point and authorization

Implement an operator-only command in the Auth application, for example `python -m app.cli.recover_admin`. It must run locally on the DGX with access to the configured Auth database and secrets. It must not be an unauthenticated HTTP endpoint, a public route, or an environment-variable password reset. Require all of the following before mutation:

1. Operator authenticates to the host using the approved named account and records the incident/change ticket.
2. A second authorized person verifies identity through an established out-of-band channel and approves the exact target `user_id=1` and `admin@omnibioai`. Record approver identity and ticket; do not treat possession of the machine alone as identity proof.
3. The command requires exact target ID, email, and ticket confirmation. It fails closed if the row is missing, email differs, status is not active, or the Admin role is absent. It never creates, activates, renames, or changes roles.
4. The command prompts twice with terminal echo disabled. Password is not accepted as an argument, environment variable, file, or standard input redirection. No prompt values, verifier, MFA secret, or recovery code may enter logs or audit metadata.

An authenticated platform-admin API may be added for recovery of another user, gated by the existing `manage_all_orgs` permission and separation of duties. It cannot be the recovery route for the sole locked-out Admin, because it requires an already-valid administrator session. The operator command remains the break-glass path.

## Mutation service contract

All entry points must call one `credential_recovery_service` and share one transaction:

- Re-read and lock the target row; validate ID, exact current email, active status, and existing Admin role.
- Call `validate_new_password(password, user.email)` and use `hash_password(password)`, which selects the configured `bcrypt_sha256` scheme. Do not directly update a database column from a script or SQL client.
- Do not alter user ID, email, roles, status, organization membership, or MFA state unless an explicit, separately authorized MFA recovery was selected.
- Revoke persisted user sessions and refresh-token families. Add a fixed `credential_recovery` session revocation reason. If the current session service commits internally, add a `commit=False` option so password change, revocation, and audit rows commit atomically.
- Add a signed `password_recovered` audit event in the same transaction. Include actor/approver IDs where available, target ID, ticket reference, recovery channel, and counts/booleans only. Never include the password, password verifier, challenge tokens, TOTP secret, or recovery codes.
- If MFA reset was explicitly approved, call the existing MFA reset service with a transaction-aware `commit=False` option. Preserve its signed `MFA_RESET_BY_ADMIN` event and record that reset in the recovery event. If MFA was not reset, do not modify it.
- Commit once. If policy validation, session revocation, MFA reset, audit signing, or commit fails, roll back the password update and all related changes together and emit a safe operator-facing failure without secret values.

## Login behavior for unsupported verifiers

Update `verify_password` to catch `UnknownHashError` as a failed comparison. To preserve the existing account-enumeration timing defense, it should also perform a dummy-hash verification for that case (handling an oversized candidate safely). It must return `False`; `authenticate_user` then emits the usual generic login-failure audit event and throttle behavior. The route remains HTTP 401 with a JSON body identical to other invalid credentials. No token or MFA challenge is issued for this failed primary authentication.

## MFA after recovery

If MFA was previously disabled, require the Admin to enroll TOTP immediately after first successful password login and generate recovery codes. If prior MFA was enabled and the device is inaccessible, the approved operator must explicitly authorize a reset through the existing MFA service as part of the recovery transaction. Successful password recovery alone must not satisfy or bypass an MFA challenge. The Admin then enrolls a fresh device, verifies it, and stores the one-time recovery codes in the approved secret manager.

## Revocation limit

Existing refresh-token families and persisted sessions must be revoked. Current access tokens use a default 15-minute lifetime and are not stored in the session table; absent a user token-version/JTI invalidation mechanism, they may remain accepted until expiry. The operator must therefore keep the recovery window isolated and wait at least the configured maximum access-token lifetime before declaring old access credentials unusable. A future implementation may provide immediate per-user access-token invalidation.

## Recovery method decision

There is no supported in-place recovery mechanism today. The next approved implementation step is to add the transaction-aware service and local operator command to the Auth source, review it, then validate it against an isolated synthetic Admin database. The current preparation did not apply that code to the sibling Auth repository because it is outside this workspace's writable roots.
