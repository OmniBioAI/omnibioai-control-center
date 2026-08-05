# PR11.4b — Enterprise Identity Audit Trail Foundation

Adds audit visibility for the Identity Management actions introduced
across PR11.1–PR11.4 to `admin.omnibioai.org` (the Admin Console /
`AdminApp`). This is not a new audit architecture — it extends
`omnibioai-auth`'s existing PR9 audit ledger
(`app/services/audit_service.py`, `app/db/models.py::AuditEvent`) with
the identity lifecycle events it was missing, and adds the one
retrieval endpoint that never existed. See
`docs/pr11-identity-audit-discovery.md` for the full discovery pass
this was built from.

## Architecture

```
 Admin Console UI (frontend/cc-ui)
   AuditLogsPage.tsx  ──uses──▶  audit.ts (fetch wrapper)
        ▲
        │ reached via
   navigation.ts 'audit-logs' nav item (flat page, no org-picker --
   audit events span every organization, filtered in-page)
        │
        ▼
 control-center backend (backend/src/control_center)
   routes_audit_proxy.py  ── pure HTTP relay, GET only, zero auth
                             decisions ──▶
        │
        ▼
 omnibioai-auth
   routes_platform_audit.py  (require_permission(manage_all_orgs) --
                               reused, not new)
        │
        ▼
   audit_service.list_events() + resolve_display_fields()
        │
        ▼
   audit_events table (written to by user_admin_service.py,
   apikey_service.py, oauth_client_service.py, org_sso_service.py --
   plus the 8 event types PR9 already wrote: login, role, permission,
   org-membership)
```

Three layers, each doing exactly one job:

1. **`AuditLogsPage.tsx`** (`frontend/cc-ui/src/pages/audit/`) — table
   (Timestamp / Event / Actor / Organization / Target / Details) with
   filters (organization, event type, actor user ID, date range) and a
   row-detail modal. Reached directly from the "Audit Logs" nav item —
   unlike the SSO/Service-Accounts pages, there's no org-picker step,
   because the backend endpoint this page reads is platform-wide, not
   org-scoped (`manage_all_orgs`, not `manage_sso`/`manage_api_keys`).
2. **`routes_audit_proxy.py`** (`backend/src/control_center/api/`) — a
   pure relay for the single `GET /platform/audit-events` route,
   following the exact shape of every other proxy file in this repo.
   Defines **GET only** — no PATCH/PUT/DELETE is proxied, because
   `omnibioai-auth` exposes none for audit events (see Security below).
3. **`omnibioai-auth`'s `routes_platform_audit.py`** — the one new
   route this PR adds on the backend. Everything it reads from
   (`audit_service.list_events`, `resolve_display_fields`) and
   everything that *writes* the events it returns
   (`user_admin_service.set_user_status`, `apikey_service.
   create_api_key`/`revoke_api_key`, `oauth_client_service.
   create_oauth_client`/`revoke_oauth_client`, `org_sso_service.
   configure_sso`/`update_sso_config`/`set_enforced`) all live in
   `omnibioai-auth`, unchanged in shape from PR9's own convention: a
   `log_event` call inside the service function, at the exact point
   the mutation happens, never in a route handler.

## Security

### Immutability

Structural, not a convention: only a `GET` route exists for audit
events, at both layers (`routes_platform_audit.py` in `omnibioai-auth`,
`routes_audit_proxy.py` in control-center's backend). No
`PATCH`/`PUT`/`DELETE` route has ever existed for a single audit event
and none is added by this PR — confirmed by a dedicated test
(`test_audit_events_are_immutable_no_update_or_delete_route` in
`omnibioai-auth`, `test_no_delete_route_exists` in the proxy suite)
asserting `404`/`405` for both.

### Secret exclusion

Every `log_event` call site this PR adds writes only display-safe
fields — names, scopes, statuses, provider types, issuer URLs, booleans
— never a plaintext key, a client secret, a secret hash, or a token.
This is verified two independent ways:

1. **At the source**, in `omnibioai-auth`:
   `tests/test_pr11_identity_audit.py`'s `_assert_no_secret_leakage`
   helper checks every new event's `before_state`/`after_state`/
   `metadata` for `super-secret`, `client_secret`, `key_hash`,
   `client_secret_hash`, `client_secret_encrypted` substrings, run
   against the API-key, OAuth-client, and SSO-config creation tests
   (the three flows that ever handle a real secret).
2. **Defense-in-depth on display**, in the Admin Console:
   `audit.ts`'s `maskSensitiveFields()` masks any key in
   `before_state`/`after_state`/`metadata` whose *name* matches
   `/secret|token|password|api_?key|client_secret|hash/i` before the
   detail modal ever renders it — independent of and in addition to
   the backend guarantee above, not a replacement for it. Covered by
   `AuditLogsPage.test.tsx`'s masking test, which deliberately injects
   a `client_secret` key into a mock event's metadata to prove the UI
   would catch it even if a future backend call site made a mistake.

### Actor attribution

Every write path this PR adds threads a real `actor_user_id` through
to `log_event` — for API key / OAuth client revocation specifically,
this required adding a new, backward-compatible `actor_user_id:
int | None = None` keyword parameter to `apikey_service.revoke_api_key`
and `oauth_client_service.revoke_oauth_client` (neither had one
before), populated from the same `membership.user_id` their routes
already resolve via `require_org_permission_or_platform_admin`. A
platform admin acting on an organization they don't belong to still
generates an attributable event — the `manage_all_orgs` bypass changes
*who is allowed to act*, never *whether the action is attributed*.

### Organization context

`organization_id` is populated wherever the action is genuinely
org-scoped (API keys, OAuth clients, SSO). It is deliberately `None`
for `user_enabled`/`user_disabled` — `PATCH /platform/users/{id}` is a
cross-tenant, platform-admin action with no single organization in
scope (a user may belong to several organizations or none); the field
reflects that honestly rather than guessing one.

### Permissions

**No new permission was introduced.** `GET /platform/audit-events`
reuses `manage_all_orgs` — the same permission every other
`/platform/*` read endpoint in `omnibioai-auth` already requires.
There is no dedicated "audit" permission registered anywhere in
`app/core/permission_names.py`, and this PR doesn't add one; per its
own instructions, one would only be introduced if the existing model
couldn't express the requirement, and it already does.

## Limitations

Explicitly out of scope, per this PR's own instructions:

- **No SIEM export.** Events live only in `omnibioai-auth`'s own
  database; there is no forwarding to Splunk, Datadog, or any external
  log pipeline.
- **No compliance reports.** No SOC2/HIPAA-formatted export, no
  scheduled report generation.
- **No retention policies.** Audit rows are never pruned or archived —
  the table grows without bound today, same as the pre-existing PR9
  events it extends.
- **No alerting.** No notification (email, Slack, webhook) fires on
  any event type, including sensitive ones like `sso_enforcement_changed`
  or `user_disabled`.
- **SSO break-glass override is not audited.** `org_sso_service.
  set_sso_override`/`clear_sso_override` — the platform-admin
  break-glass bypass introduced in Phase 2 PR5 — emit no audit event.
  This PR's required-events list (per its own task) covers SSO
  configuration create/update and enforcement changes only, not the
  override endpoints specifically. Flagged here explicitly as a real
  gap for a follow-up PR, not silently left uncovered: a break-glass
  action is exactly the kind of event an audit trail exists to catch,
  and its absence here is a scoping decision worth revisiting, not an
  oversight.
- **Actor filtering is by numeric user ID only**, not by searching an
  email — `GET /platform/audit-events` has no user-search parameter
  (only exact `actor_user_id`), so the Admin Console's filter is a
  plain numeric input rather than a searchable dropdown like the
  organization filter. A future PR adding user search to this endpoint
  would let this filter improve without any UI redesign.
