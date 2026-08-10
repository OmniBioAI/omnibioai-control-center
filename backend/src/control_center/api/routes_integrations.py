"""
control_center/api/routes_integrations.py

PR-B6: read-only status for the third-party integrations already wired
into this deployment's own docker-compose (omnibioai-studio's own
compose file, control-center's service block) -- not a generalized
"integrations platform." Discovery (see this PR's own report) found no
Integration model/table/CRUD API anywhere in the ecosystem; the only
concrete, evidenced integrations are the three below. Same shape and
same reasoning as routes_cloud.py's GET /cloud: env-var presence only,
no live connectivity check (none exists for any of these three), no
credential value ever returned.

Deliberately unauthenticated at the router level, same as cloud_router/
llm_router/infra_router (see main.py's own comment on why
services_router/summary_router/config_router/docker_router are gated
and these are not) -- this response contains no hostnames, LAN IPs,
container inventory, or credential values, only booleans and static
labels/purposes, so it doesn't fall into the "leaks internal topology"
category that earned those four routers their gate. Admin Console
visibility is controlled entirely by navigation.ts's hasAdminAccess()
nav gate, same as Cloud/LLMs/Settings.

Sentry is one provider with two independently-configurable capabilities
(SDK crash reporting vs. the Ecosystem Report's read-only query into
Sentry's own API -- see scripts/sections/health.py), so it's one entry
with two flags rather than two entries. Discord is genuinely two
separate webhook targets (checks/known_issues.py's own comment: "Separate
from DISCORD_WEBHOOK_URL"), independently configurable, so it's two
entries.
"""
from __future__ import annotations
import os
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/integrations")
def get_integrations() -> JSONResponse:
    # Read at request time, not at import time, so tests can
    # patch.dict(os.environ, ...) per-case -- same convention
    # routes_cloud.py's get_cloud() already established.
    sentry_dsn = os.environ.get("SENTRY_DSN", "")
    sentry_api_token = os.environ.get("SENTRY_API_TOKEN", "")
    sentry_org = os.environ.get("SENTRY_ORG", "")
    sentry_project_slugs = os.environ.get("SENTRY_PROJECT_SLUGS", "")

    discord_webhook = os.environ.get("DISCORD_WEBHOOK_URL", "")
    discord_alert_webhook = os.environ.get("DISCORD_ALERT_WEBHOOK_URL", "")

    return JSONResponse({
        "sentry": {
            "label": "Sentry",
            "purpose": "Error tracking (SDK crash reporting) and error aggregation for the Ecosystem Report",
            "configured": bool(sentry_dsn),
            # Mirrors scripts/sections/health.py's own gate exactly (token
            # AND org AND at least one project slug) -- the Ecosystem
            # Report's error-aggregation section is skipped otherwise.
            "report_aggregation_configured": bool(sentry_api_token and sentry_org and sentry_project_slugs),
        },
        "discord_notifications": {
            "label": "Discord – Notifications",
            "purpose": "General deploy, GPU-temperature, and disk-space alerts",
            "configured": bool(discord_webhook),
        },
        "discord_alerts": {
            "label": "Discord – Known-Issue Alerts",
            "purpose": "High-severity known-issue alerts, separate from general notifications",
            "configured": bool(discord_alert_webhook),
        },
    })
