# Canonical local Admin recovery path

Canonical code path: `app/cli/recover_admin.py` → `app/services/credential_recovery_service.py` → existing Auth policy, password hashing, MFA, session, refresh-token, and audit services.

The recovery CLI is deliberately not an HTTP route. It consumes a short-lived Ed25519 Platform Owner approval from a protected local file, resolves the target by stable user ID, validates exact email/active/global-Admin/disabled-verifier state, binds the named OS operator, prompts for password twice using `getpass`, requires exact target/ticket confirmation, and commits the password verifier, one-time approval claim, any explicitly approved MFA reset, session/refresh revocation, and audit event together.

`scripts/recover_local_password.py` is a second, less constrained sudo-based mechanism. It is not selected as authoritative and is left untouched pending owner approval; do not use it for Admin recovery.

The path is **not production-ready**: existing access JWTs can remain accepted until expiry because this recovery service does not revoke their JTI or bump an access-token epoch checked on every request. A P0 design/implementation/test is required before any live use. No recovery was run against the DGX identity.
