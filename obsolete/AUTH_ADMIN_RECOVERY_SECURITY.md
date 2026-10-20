# Administrator recovery security notes

## Authorization and trust boundaries

The recovery command is local-only and has no HTTP route. Unix root or database access alone does not authorize a reset: a valid short-lived Ed25519 approval from an active Platform Owner is required, and that approval binds the stable target ID, exact current email, disabled-verifier state, named OS operator, ticket, identity-verification reference, and optional MFA-reset scope. The approving user must hold active global `platform_admin` and `admin` roles and cannot be the target.

The private signing key remains outside Auth and the DGX execution environment. Auth trusts only the root-owned, non-writable public key at `/run/secrets/auth-recovery-approval-public-key.pem`. The protected execution image/runtime must not allow the recovery operator to replace the executable or trust anchor. Approval documents should be retained in the organization's controlled ticket/approval system; Auth audit events retain their identifiers and outcome metadata.

The command checks the target by stable ID and exact approved email, and requires exact interactive target confirmation. It requires an active global Admin and a missing/unsupported password verifier. A supported existing credential is always refused by this recovery command; any future enabled-password reset requires a separate approved workflow.

## Credential and identity protections

- Password values are accepted only through two no-echo `getpass` prompts. They are not CLI arguments, environment values, files, shell history, or audit fields.
- Auth's existing `validate_new_password` and `hash_password` functions are the only password policy and hashing paths used.
- User ID, email, account status, roles, memberships, tenants, and license associations are not modified.
- Unsupported verifier login attempts are handled as generic failures and spend a dummy bcrypt_sha256 verification where the candidate size permits.
- Passwords, password verifier values, raw tokens, TOTP secrets, and recovery codes are excluded from recovery logs and audit metadata.

## Single use, race protection, and rollback

The signed approval has a short expiry and a UUID. Its UUID is claimed in the existing unique `revoked_tokens.token_jti` column before recovery writes; the claim is namespaced and committed in the same transaction. A second process cannot claim the same UUID. A conditional `UPDATE` additionally changes the password only if ID, email, active status, and the originally observed disabled verifier still match. This prevents two distinct approvals from overwriting each other after one has recovered the target.

Session rows, all refresh token rows (including legacy rows without a session backfill), session-revocation audit events, optional MFA reset, the password verifier, approval claim, and `credential_recovery_completed` audit event share one transaction. Database or audit failure rolls the complete operation back. No database schema migration was added.

Refresh sessions and refresh tokens are revoked. Access tokens are stateless and are not tied to the refresh-session row; they can remain usable until their configured expiry (default 15 minutes) unless another existing access-token invalidation check rejects them. Keep the recovery window controlled for at least that maximum lifetime.

## MFA

Recovery without `allow_mfa_reset=true` preserves enabled MFA. Password login still returns the ordinary MFA challenge, and a valid TOTP/recovery factor is required before tokens are issued. The isolated test completes a TOTP challenge after password recovery.

If the Admin cannot use an enrolled factor, the signed Platform Owner approval must explicitly include `allow_mfa_reset=true`. The recovery service calls the existing `mfa_service.reset_user_mfa` in the same transaction, preserving its `MFA_RESET_BY_ADMIN` audit event. This is an explicit owner-authorized reset; there is no sole-Admin or unauthenticated MFA bypass. The Admin must then enroll a fresh TOTP factor and generate/store new recovery codes through the existing self-service MFA routes.

## Password history limitation

The current Auth schema has no password-history store, and the existing policy has no account-specific reuse list. Because this recovery is limited to a disabled/unsupported current verifier, Auth cannot determine whether a proposed password was used by this account before the verifier was disabled. It rejects weak/common and known-compromised candidates using the existing controls, but cannot guarantee historical non-reuse without adding and migrating password-history storage. This implementation deliberately adds no migration. The operator must choose a newly generated unique password; historical reuse rejection remains a follow-up requirement if strict technical enforcement is required.
