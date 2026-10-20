# Admin credential root cause

## Finding

The authoritative local account is the existing active Admin identity `admin@omnibioai`, stable user ID `1`. Its role and account status are intact. Its stored password verifier is a disabled/unsupported marker, not a verifier recognized by the Auth service's configured Passlib context. The verifier itself is intentionally not reproduced here.

`app/core/security.py::verify_password` currently catches `PasswordSizeError` but allows Passlib `UnknownHashError` to escape. `app/services/auth_service.py::authenticate_user` calls that helper for an active account with a password field. The uncaught exception reaches `POST /auth/login` and produces HTTP 500 instead of the route's normal JSON 401. It does not indicate that a submitted password is simply wrong.

The safe login behavior is to treat an unknown verifier as a failed password check, perform the same dummy-hash verification used for other non-verifiable accounts to limit timing differences, and return through the existing generic failure path. The login route then returns the same `{"detail":"Invalid credentials"}` JSON response as a wrong password, logs a generic login failure, and applies the existing throttle. It does not activate the account, mint tokens, or skip the normal MFA gate.

## Credential lifecycle

- Password enrollment is available only through `POST /auth/register`, which creates a new identity and rejects an existing email. It cannot enroll a password for user ID 1.
- There is no password change, password reset, recovery, invitation activation, or admin password-reset endpoint in the inspected Auth source.
- New passwords are hashed with Passlib's `bcrypt_sha256` default. Verification also recognizes legacy `bcrypt` hashes.
- `validate_new_password` applies configured length bounds (defaults 12–128), rejects the account email and a local common-password list, and runs the configured Have I Been Pwned k-anonymity check. The network check is fail-open by default when unavailable; deployments can configure fail-closed behavior. Policy failures use one generic public message.
- MFA enrollment and challenge handling exist. An authenticated user can enroll TOTP using `/users/me/mfa/totp/enroll`, verify it at `/users/me/mfa/totp/verify`, and obtain recovery codes at `/users/me/mfa/recovery-codes`. Login issues an MFA challenge when required; `/users/me/mfa/challenge` completes it. Admin MFA reset exists at `POST /platform/users/{id}/mfa/reset`, but it requires an already-authenticated platform administrator and therefore cannot recover a sole locked-out Admin.
- Session revocation exists in `auth_service.revoke_all_sessions_for_user`; it revokes refresh-token families and persisted sessions. Access tokens have a default 15-minute lifetime and are not represented by a revocable per-user session row, so they can remain usable until expiry unless a separate token invalidation mechanism covers them.
- Audit events are signed through the shared audit service. Login and MFA/session events exist. There is no password-recovery audit event because password recovery is not implemented.

## Recovery availability

No existing secure recovery endpoint can handle this disabled verifier. The registration endpoint is not suitable, and the current MFA-reset API is unavailable to the locked-out sole Admin. Directly editing the password field would bypass the supported hasher, policy, revocation, and audit transaction and is not an acceptable recovery method.

The proposed supported method is an operator-authorized, local Auth recovery command implemented on top of a shared credential-recovery service. It must prompt for the new password using a no-echo terminal prompt (never a command-line argument), verify ID/email/active Admin role, apply the normal password policy and `hash_password`, optionally reset MFA only with explicit approval, revoke refresh sessions, and commit the identity change and signed audit record atomically. The runbook remains gated until that implementation is reviewed and made available in the local Auth runtime.

## Fix verification boundary

The defensive `UnknownHashError` handling was applied only to a disposable copy under `/tmp/omnibioai-auth-recovery-20261017`. In a network-disabled container, synthetic checks confirmed a disabled marker returns `False`, a synthetic valid hash verifies, and a wrong synthetic password is rejected. No Auth source in the sibling repository, running service, live database, or Admin credential was changed. An HTTP-level regression test and the recovery workflow still require implementation in the Auth source repository and isolated integration validation.
