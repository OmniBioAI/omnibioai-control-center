# Auth Admin recovery acceptance

## Acceptance summary

The local Auth source now contains the disabled-verifier fix, a signed-approval operator command, a transaction-bound recovery service, and isolated regression tests. The Auth checkout's existing user changes were preserved. No live service/database, production identity, password, MFA setting, email, or license was changed; no deployment or migration was performed.

| Requirement | Result |
|---|---|
| Unsupported verifier produces controlled generic JSON 401 | PASS; HTTP regression test |
| bcrypt and bcrypt_sha256 remain supported | PASS |
| Operator recovery is not an HTTP route | PASS |
| Signed short-lived Platform Owner approval is required | PASS |
| Target ID/email/current disabled state and confirmation are checked | PASS |
| New password uses existing policy and bcrypt_sha256 hasher | PASS |
| Password is entered without CLI args or terminal echo | PASS |
| ID, email, status, roles, tenant and license associations are preserved | PASS; exercised identity/role preservation |
| Refresh/session invalidation and signed audit are atomic | PASS; audit failure rollback tested |
| MFA remains enforced unless signed approval explicitly authorizes reset | PASS; TOTP challenge and approved-reset tests |
| Single-use and concurrent recovery protection | PASS; separate approvals in concurrent test commit at most once |
| Password history reuse rejection | PARTIAL; no password-history store exists in current Auth schema |
| Focused recovery suite | PASS; 14 passed |
| Broader relevant suite | PASS; 253 passed, 2 skipped |
| Full Auth suite | PARTIAL; 1,572 passed, 52 failed, 35 skipped in this dirty checkout/test image |
| Live recovery / production deployment | NOT EXECUTED |

## Known constraint

Auth has no historical password verifier records or password-history table. The current disabled marker cannot establish whether a candidate was previously used by this account. The current policy still rejects out-of-policy, common, email-matching, and known-compromised choices, but it cannot technically enforce historical non-reuse. Adding that guarantee requires a reviewed password-history design and schema migration, which is outside this no-migration workstream. Operators must choose a newly generated unique password.

## Final status

`FINAL_STATUS=PARTIAL`. The isolated implementation and recovery qualification passed. The full Auth suite has unrelated failures in the existing dirty checkout/test environment, and technical historical password-reuse detection is unavailable without additional schema support. Live recovery remains prohibited.
