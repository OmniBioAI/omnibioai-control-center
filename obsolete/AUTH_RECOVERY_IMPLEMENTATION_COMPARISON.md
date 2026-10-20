# Auth recovery implementation comparison

Scope: read-only review of the Auth checkout at `ffca316a53136e284cefc791c726e6453fe38b6f` plus its existing uncommitted changes. No live Auth container or database was queried or modified.

## Implementations

| Concern | Signed recovery CLI + service | `scripts/recover_local_password.py` |
|---|---|---|
| Approval | Ed25519 approval from a root-owned pinned public key; strict fields, expiry, max 30-minute lifetime | No signed approval; relies on `sudo`/PAM |
| Identity binding | Stable user ID, exact email, active global Admin role, disabled/unsupported verifier; approval also binds operator and ticket | Email lookup only; no stable-ID or Admin-role requirement |
| Authority | Signed approval must name an active distinct user holding global `platform_admin` and `admin` roles | Any non-root sudo caller can target any active account |
| Password | Existing policy + `bcrypt_sha256` hasher, interactive `getpass`; no password argument | Existing policy + same hasher, interactive `getpass` |
| Transaction | Password, one-time approval claim, MFA change, session/refresh revocation, and audit share one DB transaction; errors roll back | Credential/session/audit writes are grouped in a DB transaction but no disabled-state CAS, signed approval, or one-time claim |
| Audit | Structured recovery completion event identifies approval, operator, approver, ticket, and session-revocation outcome without password material | Operator OS account and target are recorded in a generic event |
| Session revocation | Revokes UserSession and refresh token rows | Revokes UserSession and refresh token rows |
| MFA | Preserved by default. Reset requires explicit signed approval and uses existing MFA reset service; no bypass | Preserved, with no dedicated audited re-enrollment authorization |
| Replay/concurrency | Approval ID is claimed in `RevokedToken` under unique `token_jti`; claim commits atomically with recovery; row lock/CAS protects target | No approval to replay; concurrent update can overwrite a password |

## Finding and canonical choice

The canonical implementation is `app/cli/recover_admin.py` calling `app/services/credential_recovery_service.py`. It is the only implementation with strong approval, identity, disabled-state, replay, and concurrent-use controls. `scripts/recover_local_password.py` is a conflicting duplicate, not an acceptable equivalent. It remains in place pending owner approval; this audit does not delete or modify it.

Both commands are local and do not add a public recovery endpoint. Both revoke persisted refresh/session state. Neither provides immediate revocation of already-issued access JWTs during recovery: recovery does not blacklist each access-token JTI or write a per-user credential/session epoch that access-token validation checks. This is an unresolved P0 acceptance blocker.

## Approval properties

- Expiration: parsed timezone-aware timestamps; `issued_at` may be at most 60 seconds ahead; expiry must be in the future; signed lifetime is positive and no longer than 30 minutes.
- Signer authorization: signature verifies against the pinned Ed25519 public key; approver user ID must resolve to an active, distinct global user with both `platform_admin` and `admin` roles.
- Named operator and target: service compares the active OS login supplied by CLI to signed `operator_login`; stable target ID, exact target email, active state, global Admin role, disabled verifier, and typed confirmation are checked.
- One-time use: namespaced approval UUID is inserted into uniquely constrained `RevokedToken.token_jti` in the same transaction as recovery. Replay is rejected. A concurrent unique-key collision cannot commit a second recovery.
- Restart persistence: after successful commit, the replay claim is a normal durable database row, so it survives process restart. Tests qualify replay in a new SQLAlchemy session, not a database/process restart; actual crash/restart persistence is inferred from the durable MySQL transaction and schema uniqueness, not separately crash-tested.

## Auth disabled-verifier response

The login verifier maps unsupported/disabled password markers to the same generic JSON 401 (`{"detail":"Invalid credentials"}`) as an unknown account, while running a dummy verifier check. It does not activate the account or bypass MFA. HTTP behavior was exercised in the disposable-MySQL recovery tests.
