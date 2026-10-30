# Users, plan and storage consolidation

The admin console has one Users navigation item. Legacy `/tenants` links replace
browser history with `/users`; `/tenants/:id` opens
`/users/:id?tab=plan-storage`. Profile retains identity, status, roles and
organization membership controls. Security retains authentication and MFA.
Plan & storage reuses the tenant detail and audited actions, mounted only with
`manage_all_orgs`. Compute and API remain coming-soon tabs; no corresponding
user functionality existed previously.

Users retains Email, Status, Global Roles, Organizations, Last Login, Auth Method,
Created and Actions, and adds Plan/Promo, Used / Allocated and Valid until.
Existing organization/status/role filters remain, together with plan, plan source,
membership, validity and storage filters. Search covers username/email/id. CSV
exports every matching page (200 rows per request), including identity and plan
columns, escaping spreadsheet formulas. The table defaults to 50 rows.

## Aggregation and freshness

`GET /admin/tenants` performs global filtering and deterministic sorting against
a Control Center index, then resolves Auth, Billing and Workbench concurrently
for only that page's IDs. The API default is 50; the maximum is 200. No list
request waits for a complete Billing/Workbench scan. Existing organization-role
semantics are preserved through Auth's filtered directory endpoint.

Billing and Workbench currently only offer batch-by-ID resolution, with no global
filter/summary endpoints. A background refresh therefore builds the global index
using existing endpoints, once per 60 seconds of activity per credential per
process, with concurrent callers sharing one refresh. The bounded cache holds at
most eight credential hashes and never persists bearer tokens. This requires no
changes or releases in Auth, Billing or Workbench.

Cold list requests return 503 with Retry-After: 2 while that background job warms
the index. The UI retries for up to one minute, then offers Retry. Cold and
expired summary requests await the shared refresh; summaries are cached for 60
seconds and a failed refresh is surfaced rather than labeled fresh. Warm lists
can use the previous index while a refresh runs (or fails); the API includes
`index_age_seconds`. Counts/filter membership reflect the index snapshot, while
page plan/storage values are resolved live. External changes can therefore take
a refresh to affect filtering. Admin plan/storage actions invalidate the cache
and their refreshed detail immediately updates existing indexed rows. Cache state
is process-local; each worker and newly authenticated credential warms separately.

## Local validation

- Frontend: `npm test -- --reporter=dot` (full suite).
- Backend: tenant routes/service/pagination, nginx routing, core auth and JWT
  regression tests using `/tmp/auth-venv/bin/python`, `PYTHONPATH=backend/src`,
  and `-o addopts=''`. Upstream calls are mocked; these targeted checks do not
  claim the repository-wide coverage threshold.
- Admin build: `VITE_TENANTS_MOCKS=false VITE_APP_MODE=admin npm run build:admin`.
- Performance test: 2,425 indexed users, global filters before pagination, exactly
  50 page IDs resolved. Warm API request measured approximately 27 ms locally
  with mocked upstreams and asserts less than one second. Production latency,
  upstream query cost, initial warm-up and multiworker behavior were not measured.
- An attempted broader user-proxy test collection required `sentry_sdk`, absent
  from the available Python environment; that broader suite was not run.

## Release scope

Release **control-center** and **control-center-web** together. No schema changes,
new environment variables, migrations, or upstream service releases are needed.
No deployment or live smoke test was performed. Commit and merge messages use
`[skip ci]`; validation is local only.
