# Disabled password verifier handling

## Change

`omnibioai-auth/app/core/security.py::verify_password` now catches Passlib `UnknownHashError` and returns `False`. Before returning, it verifies the submitted value against the existing dummy bcrypt_sha256 hash to preserve the timing behavior used for unknown users and password-less accounts. If the input exceeds Passlib's supported verification size, `PasswordSizeError` is caught and the comparison still returns `False`.

Existing `bcrypt` and `bcrypt_sha256` verification remains unchanged. A disabled or unsupported verifier can never authenticate. `authenticate_user` takes the ordinary invalid-password branch, so `/auth/login` produces the existing generic JSON 401, writes a generic login-failure event, and applies existing throttling. No account status, MFA state, or token flow is changed by this fix.

The regression test exercises the HTTP route for a disabled verifier and compares it with an unknown-email response. It checks status, JSON Content-Type, generic response body, no exception disclosure, and no synthetic password in captured logs. It also tests oversized input and both supported verifier schemes.

## Verification

`tests/test_admin_credential_recovery.py`: 14 passed in the isolated Auth test container. The entire Auth suite was also run against the disposable source copy; its outcome and unrelated failures are recorded in `AUTH_ADMIN_RECOVERY_TEST_RESULTS.md`.

No live Auth process or database was changed.
