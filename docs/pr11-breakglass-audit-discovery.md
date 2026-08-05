# PR11.4c — Enterprise Break-Glass Audit Completion: Discovery

Small follow-up to PR11.4b, discovery performed before coding per this
PR's own instructions. Verified directly against `omnibioai-auth`
source (both `org_sso_service.py` and its route caller), not assumed.

## 1. `org_sso_service.py`: `set_sso_override` / `clear_sso_override`

Both functions and the `audit_service` import already exist,
unchanged since PR11.4b (which added the import for the sibling
`SSO_CONFIGURATION_*`/`SSO_ENFORCEMENT_CHANGED` events but never
touched these two override functions — confirmed by grep, no
`audit_service` reference inside either).

```python
def set_sso_override(
    db: Session, config: OrganizationSSOConfig, reason: str, actor_user_id: int
) -> OrganizationSSOConfig:
    """Global-admin break-glass bypass: suspends the *effect* of
    `enforced` for this org without changing `enforced` itself...
    Deliberately overwrites any prior override (re-triggering it just
    updates who/why/when, not an error) -- idempotent from the
    caller's perspective."""
    config.sso_override_at = datetime.utcnow()
    config.sso_override_reason = reason
    config.sso_override_by_user_id = actor_user_id
    db.commit()
    db.refresh(config)
    return config


def clear_sso_override(db: Session, config: OrganizationSSOConfig) -> OrganizationSSOConfig:
    config.sso_override_at = None
    config.sso_override_reason = None
    config.sso_override_by_user_id = None
    db.commit()
    db.refresh(config)
    return config
```

### Where `actor_user_id` is available

- **`set_sso_override`** already takes `actor_user_id: int` as a
  required parameter — no change needed, mirror
  `configure_sso`/`update_sso_config`/`set_enforced`'s existing
  pattern exactly.
- **`clear_sso_override` has no `actor_user_id` parameter at all** —
  the same gap PR11.4b found and fixed for
  `apikey_service.revoke_api_key`/`oauth_client_service.
  revoke_oauth_client`. Its caller,
  `routes_org_sso.py::clear_sso_override` (the route, same name as
  the service function — distinct symbols), already resolves the
  caller via `require_permission(OVERRIDE_SSO_ENFORCEMENT)` and
  already computes `int(user["sub"])` for the sibling `POST /override`
  route one function above it — it's simply never passed down to
  `clear_sso_override` today. This PR adds a new, backward-compatible
  `actor_user_id: int | None = None` keyword parameter to
  `clear_sso_override`, the same shape PR11.4b's revoke-function fix
  used, and updates the route to pass `int(user["sub"])`.

### Organization context

Both functions receive the already-loaded `config` (an
`OrganizationSSOConfig` row), so `config.organization_id` is directly
available in both — no extra query needed, same as every other
SSO-related audit call site PR11.4b added.

### Current override model fields

`OrganizationSSOConfig` (confirmed in `app/db/models.py`, unchanged):
`sso_override_at` (`DateTime | None`), `sso_override_reason`
(`str | None`), `sso_override_by_user_id` (`int | None`). An override
is "active" exactly when `sso_override_at is not None` — the same
condition `routes_org_sso.py::_to_out`'s `sso_override_active` field
already uses. No new column is needed; before/after audit state is
built entirely from these three existing fields plus `config.enforced`
(unchanged by either function, but relevant context for what the
override is doing).

## 2. Existing `AuditEventType` / `audit_service.log_event` pattern

Both already exist from PR11.4b, reused as-is:

```python
class AuditEventType:
    ...
    SSO_CONFIGURATION_CREATED = "sso_configuration_created"
    SSO_CONFIGURATION_UPDATED = "sso_configuration_updated"
    SSO_ENFORCEMENT_CHANGED = "sso_enforcement_changed"
```

`log_event(db, event_type, actor_user_id=None, target_user_id=None,
organization_id=None, resource_type=None, resource_id=None,
before_state=None, after_state=None, metadata=None)` — never raises,
rolls back and logs on failure, called from inside the service at the
exact point the mutation happens. This PR adds exactly two new
constants (`SSO_OVERRIDE_CREATED`, `SSO_OVERRIDE_REMOVED`) and two new
call sites, following the identical shape every PR11.4b call site
already established (e.g. `set_enforced`'s "only emit on an actual
value change" convention — see §3 below).

## 3. Scope decisions this discovery settles

1. **`clear_sso_override` gains an `actor_user_id` kwarg**, same
   backward-compatible pattern PR11.4b already used twice
   (`revoke_api_key`, `revoke_oauth_client`) — the one small,
   necessary service-signature change this PR makes.
2. **`SSO_OVERRIDE_CREATED` is emitted on every `set_sso_override`
   call**, including a re-trigger of an already-active override — the
   function's own docstring frames re-triggering as a deliberate,
   meaningful action ("updates who/why/when"), so each one is
   independently audit-worthy, unlike a genuine no-op.
3. **`SSO_OVERRIDE_REMOVED` is emitted only when an override was
   actually active before clearing** (`sso_override_at is not None`
   beforehand) — mirroring `set_enforced`'s existing "don't log a
   no-op" convention exactly. Calling `DELETE /override` on a config
   with no active override today silently no-ops (resets already-`None`
   fields to `None`) and returns 200; this PR doesn't change that
   behavior, it just doesn't manufacture an audit event for it.
4. **Metadata never includes `client_secret`,
   `client_secret_encrypted`, or any token** — override
   creation/removal never touches those fields at all (they're
   untouched by `set_sso_override`/`clear_sso_override`), so this is
   automatic by construction, verified directly by a test (same
   `_assert_no_secret_leakage`-style check `test_pr11_identity_audit.py`
   already established in PR11.4b).
5. **No new endpoint, no new permission** — `POST /orgs/{org_id}/sso/override`
   and `DELETE /orgs/{org_id}/sso/override` already exist and already
   enforce `override_sso_enforcement` (global-scoped, deliberately not
   org-scoped — a platform-operator break-glass tool that must work
   even if the org's own admin is locked out); this PR only adds audit
   calls inside their already-existing service functions.
6. **No new retrieval endpoint** — `GET /platform/audit-events`
   (PR11.4b) already returns every event type without modification;
   the two new event types simply start appearing in its results once
   emitted.
7. **Frontend**: `AuditLogsPage`'s existing `KNOWN_EVENT_TYPES` list
   and `formatEventType()` (in `audit.ts`) already produce a readable
   fallback label for any unrecognized event type
   (`"sso_override_created"` → `"SSO Override Created"` via the
   existing word-splitting logic) — but the task asks for specific,
   friendlier labels ("SSO Break-Glass Override Enabled"/"...Removed"),
   which `formatEventType`'s generic transform can't produce on its
   own. This PR adds a small explicit label override map for these two
   event types only, rather than generalizing `formatEventType` for a
   one-off wording difference.
