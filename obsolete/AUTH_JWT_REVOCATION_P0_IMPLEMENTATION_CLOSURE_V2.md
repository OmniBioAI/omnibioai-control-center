# JWT revocation P0 implementation closure — V2

**Workstream:** `OMNIBIOAI_JWT_REVOCATION_P0_IMPLEMENTATION_CLOSURE_V2`  
**Mode:** isolated security remediation; no deployment or live credential recovery  
**Status:** `PARTIAL` — the canonical Auth change and high-risk consumer paths are qualified, but full cross-service HTTP qualification and release provenance are incomplete.

## Selected revocation contract

Use a monotonic per-user Auth credential epoch (`User.credential_version`) and require fresh Auth validation at every participating service's user-token authorization decision. The canonical signed local recovery service increments the epoch with a compare-and-set in the same transaction as password update, audit, MFA handling, and session/refresh revocation. Auth checks the signed token epoch against the current user row and returns invalid on mismatch. Consumers do not trust JWT signature/expiry alone as current authorization and do not use cached user identity for numeric user subjects. Auth/database/revocation-state uncertainty denies access.

This is preferable to session-only binding because current access JWTs are stateless and do not carry a reliably enforced session-family ID. An epoch is a durable, user-scoped revocation fact and preserves unrelated users. It retains the existing JTI denylist for ordinary logout/revocation and does not change signing algorithms or the MFA protocol. The new schema field is additive; no live migration was run.

Recovery path qualified in the candidate: `app/cli/recover_admin.py` → `app/services/credential_recovery_service.py`. It increments `credential_version` atomically with the other recovery effects. Numeric user IDs, exact email, active Admin state, disabled verifier, signed approval, operator, confirmation, and existing transaction checks remain in force. MFA is preserved unless explicit signed scope permits reset; successful login still requires the existing MFA challenge.

Legacy user JWTs missing `credential_version` are interpreted as epoch `0` only while `AUTH_CREDENTIAL_EPOCH_MODE=compatibility`. Incrementing a recovered user's epoch makes all such pre-recovery tokens stale. `required` rejects missing epoch claims. Do not enable `required` until all token issuers/consumers have been upgraded and the maximum legacy token lifetime/compatibility window is approved. New tokens carry the current epoch.

Service and delegated tokens are not silently reclassified as user access JWTs. Service/client-credentials and ToolServer registration credentials retain their client-status/scope/expiry/revocation contract and have no user subject. User-bound `delegated_execution` tokens include user subject and credential epoch; Auth's dedicated ToolServer introspection checks that epoch and the active delegation grant. Thus password recovery invalidates them too. ToolServer accepts delegated execution or its separate service-registration token, not a raw user JWT.

## Validator inventory and provenance

Candidate trees are under `/tmp/omnibioai-jwt-revocation-p0/`. Their scoped changes have now been committed in the isolated worktrees; existing developer worktrees and running services were not edited/replaced. No candidate has been deployed or started as a service.

| Boundary | Candidate/base revision | Validation path and cache/failure behavior |
|---|---|---|
| Auth | `654203a942e45f71e7e64d94deba27c1c2be5578` (candidate base); current local Auth source HEAD is `ffca316a53136e284cefc791c726e6453fe38b6f` | `app/rbac.py::get_current_user` / `get_optional_current_user` and `/auth/validate` use shared `assert_token_usable`: JTI revocation, active user, current epoch, and identity check. `app/api/deps.py` was also hardened to use the shared validator even though current Auth routes do not import it. Auth/DB/Redis failure does not yield an authorized user. `app/services/delegated_execution_service.py` uses its separate audience/type/grant introspection and the user epoch. |
| API Gateway | `d2343b9aa60ebfe0b997883ebac554b47e911aa4` | `app/middleware/auth.py` → `app/services/iam_client.py::validate`; local signature/claims then Auth `/auth/validate` for numeric user subjects on each request. User identity cache is bypassed; network/invalid response denies. Service identities retain their separate lifecycle. |
| Shared IAM client | `4df6c435fea51ec8a2672e32300a9f7a3e2b5c0a` | `iam_client/client.py::get_user` / `validate_remote`; local decode is not sufficient for user subjects, cache is bypassed, remote Auth validation is mandatory and failures return no identity. Non-user service identity caching remains separate. |
| Studio | `3a02e0be7c5fcba4ae711d4e86e0264e9f08e1e8` | `backend/license_server.py::_validate_token` calls Auth `/auth/validate` and denies on invalid response/network exception. Repository scan found no other Studio backend raw JWT decoder in the reviewed backend path. That route's focused tests could not collect in available runners because `requests` is absent; no stale-token Studio HTTP claim is made. |
| Control Center | `0df959f1b2acdb8f67b02284ebfc939a8a62f39f` (candidate; current local source HEAD `0df959f`) | `backend/src/control_center/core/jwt_verify.py::verify_token` verifies signature/claims, then requires fresh Auth validation for user subjects; `core/auth.py` uses it for protected routes. Auth failure/invalid response denies; no user identity cache is used. |
| TES | `8ad9e80d64ebdebe91955c4bc033ab2d3cf45118` | `src/omnibioai_tool_exec/service/security/iam.py` validates user access via shared IAM/Auth on each decision; delegated ToolServer calls use dedicated introspection. Focused tests could not collect in available runner because `sentry_sdk` is absent. |
| ToolServer | `a0a9d2b0050497d38b07e52f1c99a15f074e96a2` | `toolserver/security.py` accepts delegated execution through `iam_client.delegated` introspection and registration through its separate Auth introspection; it does not locally accept ordinary user JWTs. Focused tests were blocked by missing `PyYAML` in the runner. |
| Workbench | `6f522174cc59e92585fbed79b468483438783923` | `omnibioai/middleware/jwt_auth.py` changed to current Auth validation for user tokens and fail-closed behavior. Test collection is unqualified here (runner lacks Django/pytest-django). |
| Security Audit | `8900c81c871ef626434d2a79442ae93be3a61005` | `audit/jwt_verify.py` changed to fresh Auth validation for user subjects. Existing suite included many offline-fixture assumptions; prior candidate run was `534 passed, 60 skipped, 31 failed`, so full suite is not qualified. |
| Dev Hub | `18419c35ca72210f1d45b277692dd7ee49b52722` | `api/auth.py` changed to fresh Auth validation for user JWTs. New targeted stale-token tests passed previously; full auth module had one unrelated collection/startup test unavailable due missing `requests`. |
| Other IAM consumers | e.g. LIMS, Billing, RAG, Model Registry, Workflow Bundles | Source review shows use of shared IAM client. Revocation is effective only after those runtimes upgrade to the uncached-user-validation client; their packaged/runtime deployments were not exercised. |

Other Auth JWT decodes found are for OAuth/SAML state, MFA challenges, refresh tokens, service credentials, or delegated/registration introspection. They are not alternate user-route authorization dependencies. The previously decode-only `app/api/deps.py` helper had no current route callers; the candidate now routes it through the shared epoch check to avoid a future bypass.

## Isolated qualification

- Auth recovery + epoch + token-revocation + duplicate-command tests on disposable MySQL 8.0.46: **30 passed, 4 warnings, 16.08s**. This used only synthetic accounts and FastAPI HTTP test requests; no production/live database. Coverage includes disabled-verifier JSON failure, bcrypt compatibility, canonical command invocation, old-token rejection through `/auth/validate` and a protected Auth route, fresh-token acceptance, unrelated-user token preservation, MFA enforcement/preservation and explicitly scoped reset, transaction rollback on audit failure, approval replay, concurrent recovery, session/refresh revocation, epoch legacy mode, dormant-helper enforcement, and Redis outage fail-closed behavior. The disposable MySQL container was removed.
- IAM client `tests/test_client.py`: **35 passed** in isolated runner.
- Gateway `tests/test_iam_client.py`: **34 passed** in isolated runner with the matching IAM candidate mounted.
- Control Center `tests/test_jwt_verify.py`: **33 passed** in isolated runner.
- Studio focused test collection: blocked (`requests` missing in both available runners).
- TES focused test collection: blocked (`sentry_sdk` missing).
- ToolServer delegated/registration tests: blocked by test-runner dependency mismatch (`PyYAML` missing; 46 errors, 16 failures, 2 passed). These are not represented as passing product tests.
- No composed real-socket Gateway/Studio/Control Center/TES/ToolServer stale-token E2E was run. Previous isolated Auth network E2E evidence is recorded in the existing `AUTH_CROSS_SERVICE_JWT_REVOCATION_P0_REPORT.md`; it does not substitute for these consumer E2Es.
- Tenant isolation is not fully qualified by this V2 run: an unrelated user's token remains valid in the Auth test, but no multi-tenant matrix was executed through every consumer.
- No full test suite, production-equivalent backup/restore, or MySQL Alembic migration rehearsal was completed in this V2 turn. Migration `0033_user_credential_epoch` is additive over `0032_manual_license_security`; run forward/rollback rehearsal against disposable MySQL before release. Do not downgrade away a nonzero epoch.

## Duplicate recovery command

`scripts/recover_local_password.py` has no in-repository caller other than its Dockerfile copy; it is not used by Auth routes. The isolated candidate replaces its entrypoint with a hard-disabled response directing operators to the signed canonical CLI. The script has not been deleted. Do not enable or use it as a live recovery command. The current Auth source worktree still contains the original executable script; its strict disablement is only in the candidate and must be reviewed/merged before any release.

## Release and rollback requirements

1. Back up Auth data and rehearse additive migration `0033` from `0032` on representative disposable MySQL. Verify existing users backfill to epoch `0`, constraints/defaults, recovery increment, audit rollback, concurrent compare-and-set, and restore.
2. Build immutable Auth and consumer artifacts from reviewed, aligned source commits. Deploy the additive schema and epoch-aware Auth in `compatibility` mode. Do not recover any live credential yet.
3. Roll out every user-token validator listed above with Auth URL, network policy, health checks, and fail-closed behavior. Service/delegated token lifecycles must pass their integration tests. Confirm no old binary/cache path authorizes numeric user subjects.
4. Run composed HTTP tests through every critical consumer: accept old token before recovery; reject it after synthetic recovery; accept newly issued token; preserve unrelated users/tenants; deny during Auth/revocation-store outage; verify MFA and delegation behavior.
5. Only after all issuers/consumers are upgraded and the legacy lifetime is addressed, consider `required` mode. This is a coordinated security setting, not a default flip for partial rollout.
6. Rollback must keep epoch-aware Auth validation and retain the epoch column/data. Do not roll consumers back to local signature-only authorization or downgrade/drop `credential_version`; that would reintroduce the P0. If a safe epoch-aware version cannot be retained, disable affected user-token authorization until a compatible version is restored.

## Provenance and final disposition

Isolated candidate commits: Auth `097818639c43b7a677b78aeffa52b73b302ea3f0`; IAM client `7657eaff5a4741b9086e270143daa518b2500a4d`; Gateway `3eeae69451182718d063200f8b33e00ffaf705e8`; Control Center `df2ae334f9290968c911fd7803209d0b9117c803`; TES `f865f90f0cec4f805675f236db12361e33549ea8`; Workbench `c664f8fd0e1e21b5dea638fd4cd2b07c4db52888`; Security Audit `bacdc6a8e1323cefc9286a9c10feb6a3656390b9`; Dev Hub `b5b147272210994de9852aac42c7f5a0a57f8f6a`. The Auth image built locally from its isolated candidate is `omnibioai-auth:jwt-revocation-p0-v2-20261017` (`sha256:79a06dd1942325ccd1b463dc30c1afb3779ab9d52ac1ccdbac8f4d93dbf06060`); it was not run or deployed. The Auth candidate base (`654203a`) predates current local Auth HEAD (`ffca316`); relevant canonical recovery files were overlaid from current local source and tested, but clean rebase/alignment against current Auth and immutable cross-service builds remain release gates. No source/live Auth repository, running Auth service, production DB/config, Cloudflare/DNS, or license issuance was changed. Only named disposable MySQL test containers were started and removed.

**Acceptance:** immediate stale-JWT rejection is demonstrated in isolated Auth and validator-unit tests. It is not yet demonstrated over real HTTP at every in-scope service, and candidate source alignment/provenance plus migration rollout remain incomplete. Therefore the closure is `PARTIAL`, not `COMPLETE`.
