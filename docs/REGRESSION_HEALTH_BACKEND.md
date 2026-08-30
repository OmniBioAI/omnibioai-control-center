# Regression Health backend integration

The Control Center exposes the reviewed RH-1 certification artifact through
the read-only, infrastructure-admin-protected backend endpoint `GET
/regression-health`, published to the Admin Console as
`GET /regression-health/data`. The backend consumes the artifact; it does not infer
certification from `reports/regression-summary.json` or from test exit status.

The deployed artifact location is configured with
`REGRESSION_HEALTH_ARTIFACT_PATH`. If unset, the backend uses
`${WORKSPACE_ROOT}/omnibioai-ecosystem-regression/status/regression-health.json`
(`WORKSPACE_ROOT` defaults to `/workspace`). The freshness threshold is
configured with `REGRESSION_HEALTH_STALE_AFTER_HOURS`, defaulting to 168 hours
(seven days). Freshness is derived metadata: a stale artifact retains its
underlying certification fields.

Missing, unreadable, unsupported, or malformed artifacts return HTTP 503 with
`STATUS_UNAVAILABLE`. An unparseable `generated_at` retains the artifact data
but reports freshness `UNKNOWN`. The API never returns the configured path,
raw parser errors, or sensitive runtime data. Deployment mounting and proxy
wiring are defined below.

## Deployment

Mount only the promoted JSON file into the backend container, read-only, at
`/app/data/regression-health.json`, and set
`REGRESSION_HEALTH_ARTIFACT_PATH` to that container path. The checked-in
Control Center compose template uses the required
`REGRESSION_HEALTH_ARTIFACT_HOST_PATH` host-file variable; it does not mount
the regression repository. The nginx API proxy publishes the API at
`/regression-health/data` and rewrites it to the backend endpoint. The
human-facing Admin Console SPA route remains `/regression-health`; keeping
these paths distinct prevents nginx from serving the API response for a
browser document navigation.

The release stack should provide the same single-file read-only mount through
its deployment-specific artifact path. The artifact is currently manually
promoted/generated; CI review and immutable publication remain a follow-up.
