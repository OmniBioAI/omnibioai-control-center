# Regression Health backend integration

The Control Center exposes the reviewed RH-1 certification artifact through
the read-only, infrastructure-admin-protected endpoint `GET
/regression-health`. The backend consumes the artifact; it does not infer
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
wiring are deferred to the deployment integration phase.
