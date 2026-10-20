# Local administrator credential recovery command

## Command

The Auth application now provides `app.cli.recover_admin`. It is a local command and is not registered as an HTTP route.

```text
python -m app.cli.recover_admin --user-id 1 --approval-file /protected/approval/admin-recovery.json
```

Run it only from the approved Auth execution environment with the designated operator's named local account and the normal protected Auth database configuration. The command requires an interactive terminal. It accepts no password argument, environment variable, or redirected input; it reads the password twice through `getpass` with terminal echo disabled. It prompts for the exact text:

```text
RECOVER 1 admin@omnibioai <ticket-id>
```

The current email stays `admin@omnibioai`. The command does not change email, status, roles, organization memberships, tenant relationships, or license associations.

## Signed approval

The command requires a signed approval record from the external/out-of-band Platform Owner approval process. The Ed25519 private key stays outside Auth and outside the DGX recovery runtime. Auth verifies the signature using the root-owned, non-writable public key mounted at:

```text
/run/secrets/auth-recovery-approval-public-key.pem
```

The key file must be a regular root-owned file, not a symlink, and not group/world writable. The signed JSON record includes these fields:

| Field | Meaning |
|---|---|
| `version` | `1` |
| `approval_id` | Unique UUID; usable once |
| `action` | `admin_credential_recovery` |
| `target_user_id` | Stable numeric Auth user ID |
| `target_email` | Exact current email expected for that ID |
| `expected_credential_state` | `disabled_or_unsupported` |
| `operator_login` | Exact OS login allowed to run the command |
| `approver_user_id` | Active Platform Owner identity in Auth |
| `ticket_id` | Change/incident approval reference |
| `identity_verification_ref` | Reference to completed out-of-band identity verification |
| `allow_mfa_reset` | Explicit signed scope; false unless separately approved |
| `issued_at`, `expires_at` | UTC timestamps; maximum approval lifetime is 30 minutes |
| `signature` | Base64 Ed25519 signature over canonical JSON fields |

The database authorizer check requires the approving identity to be active and hold both global `platform_admin` and `admin` roles. It must be a different identity from the recovery target. Approval creation is not implemented as a public Auth endpoint; the record comes from the organization's separately controlled approval authority.

## Preconditions and outcomes

The command requires the supplied user ID to resolve to an active global Admin with the exact approved email and a missing/disabled/unsupported password verifier. It refuses a supported existing password verifier, an invalid or expired signature, a different OS operator, a mismatched target confirmation, an inactive/non-Admin target, an inactive/non-Platform-Owner approver, a previously used approval, and any password rejected by `validate_new_password`.

New passwords are created through `hash_password`, which uses `bcrypt_sha256`; policy checks use the existing length bounds, account-email comparison, local common-password list, and configured HIBP check. The command reports only success/failure and counts. It never prints the entered password, verifier, approval signature, MFA secret, or recovery codes.

## Single use and transaction

The service consumes the approval in the existing uniquely constrained `revoked_tokens.token_jti` table using the namespaced value `credential-recovery-approval:<approval_id>`. It conditionally updates the user only while the approved disabled credential state is still current. The approval claim, password hash, session/refresh revocation, optional approved MFA reset, and signed audit records are committed together. There is no schema migration.

The invoker receives exit code `0` on successful commit and nonzero on denial/failure. Unexpected database/audit errors are reported generically; exception strings and SQL parameters are not printed.
