# Security Audit Explorer

Audit Explorer is the Admin Console’s read-only view of the Security Audit
durable event store. It is distinct from **Audit Logs**, which reads Auth’s
identity-audit ledger through `/platform/audit-events`.

## Architecture and authorization

The request path is:

```text
Browser → Control Center → Security Audit GET /audit/events/safe
```

Control Center forwards only the bearer authorization header and the safe
API’s allowlisted query parameters. Security Audit remains the authority for
authentication, organization scope, filtering, and safe projection. A browser
query parameter cannot establish or widen tenant authority. Platform callers
with `manage_all_orgs` may query platform-wide data; organization-scoped
callers are restricted server-side to their authorized organization and do not
receive a tenant selector.

The safe event projection currently contains event ID, timestamp,
organization ID, tenant scope, actor, event type, action, decision, integrity,
and allowlisted metadata. `service` is not present in the current safe event
projection and is shown as unavailable rather than inferred. Raw context,
request bodies, SQL, signatures, and signing keys are not exposed. Freshness
and retention remain `UNKNOWN` when the upstream source cannot establish them.

Audit Explorer exposes GET only and provides no delete, edit, replay,
acknowledge, resign, retention, or tenant-override operation.

## AE-2 release certification

Live certification verified platform-admin access, real non-empty event
rendering, supported filters, pagination, integrity badges, safe metadata
detail, empty-result `AVAILABLE` behavior, browser routing through Control
Center only, and authenticated `/audit-explorer` hard refresh.

The following are documented limitations, not fabricated fixtures:

- A populated organization-scoped browser case was not exercised because no
  supported owner identity was available for an organization containing the
  suitable existing events. Upstream tenant filtering, exclusion of `GLOBAL`
  and `UNKNOWN`, cross-tenant `403`, and an organization-scoped empty query
  were already certified.
- Browser source-unavailable rendering was not live-exercised because no safe
  temporary failure fixture exists. Backend 503 mapping and upstream safe
  failure behavior remain covered separately.
- Full-application `TestClient` tests remain affected by pre-existing
  lifecycle/scheduler teardown debt; isolated async proxy tests pass.
