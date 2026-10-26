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
import re
from urllib.parse import urlsplit
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from control_center.notifications.discord import (
    AUTOMATED_CHANNELS,
    COMMUNITY_CHANNELS,
    DiscordConfigError,
    channel_configuration_status,
    _validate_webhook,
)

router = APIRouter()


def _valid_central_alert_route(env: dict[str, str], channels: dict[str, str]) -> bool:
    router_url = env.get("DISCORD_EVENT_ROUTER_URL", "").strip()
    source_secret = env.get("DISCORD_EVENT_INFRASTRUCTURE_SECRET", "").strip()
    try:
        parsed = urlsplit(router_url)
        valid_url = (
            parsed.scheme in {"https", "http"} and bool(parsed.hostname)
            and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment
            and not (parsed.scheme == "http" and parsed.hostname not in {"control-center", "localhost", "127.0.0.1"})
        )
    except ValueError:
        valid_url = False
    valid_secret = (
        len(source_secret) >= 43 and source_secret.isascii()
        and re.fullmatch(r"[A-Za-z0-9_-]+", source_secret) is not None
    )
    return valid_url and valid_secret and all(
        channels.get(channel) == "configured" for channel in AUTOMATED_CHANNELS
    )


def _valid_legacy_fallback(env: dict[str, str], key: str) -> bool:
    if env.get("DISCORD_LEGACY_WEBHOOK_FALLBACK", "").strip().lower() != "enabled":
        return False
    if env.get("DISCORD_EVENT_ROUTER_URL", "").strip() or env.get("DISCORD_EVENT_INFRASTRUCTURE_SECRET", "").strip():
        return False
    value = env.get(key, "").strip()
    if not value:
        return False
    try:
        _validate_webhook(value, "legacy")
    except DiscordConfigError:
        return False
    return True


@router.get("/integrations")
def get_integrations() -> JSONResponse:
    # Read at request time, not at import time, so tests can
    # patch.dict(os.environ, ...) per-case -- same convention
    # routes_cloud.py's get_cloud() already established.
    sentry_dsn = os.environ.get("SENTRY_DSN", "")
    sentry_api_token = os.environ.get("SENTRY_API_TOKEN", "")
    sentry_org = os.environ.get("SENTRY_ORG", "")
    sentry_project_slugs = os.environ.get("SENTRY_PROJECT_SLUGS", "")

    env = dict(os.environ)
    try:
        discord_channel_status = channel_configuration_status()
        discord_channel_config_valid = True
    except DiscordConfigError:
        # Status is deliberately credential-free. Invalid configuration is
        # visible, but neither the bad value nor its parser error is returned.
        discord_channel_status = {channel: "invalid" for channel in COMMUNITY_CHANNELS}
        discord_channel_config_valid = False

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
            "configured": (
                _valid_central_alert_route(env, discord_channel_status)
                or _valid_legacy_fallback(env, "DISCORD_WEBHOOK_URL")
            ),
        },
        "discord_alerts": {
            "label": "Discord – Known-Issue Alerts",
            "purpose": "High-severity known-issue alerts, separate from general notifications",
            "configured": (
                _valid_central_alert_route(env, discord_channel_status)
                or _valid_legacy_fallback(env, "DISCORD_ALERT_WEBHOOK_URL")
            ),
        },
        "discord_event_routing": {
            "label": "Discord – Event Routing",
            "purpose": "Approved public events routed to least-privilege channel webhooks",
            "configured": any(value == "configured" for value in discord_channel_status.values()),
            "configuration_valid": discord_channel_config_valid,
            "channels": discord_channel_status,
        },
    })
