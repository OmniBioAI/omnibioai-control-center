"""
tests/test_routes_integrations.py

Unit tests for:
  - control_center.api.routes_integrations  (GET /integrations)

Mirrors test_routes_cloud.py's exact conventions: no upstream service
involved (env-var presence only, read at request time), so there is no
401/403/404/500-forwarding, connection-failure, malformed-JSON, or
query-param-forwarding behavior to test here -- same as GET /cloud, and
for the same reason (see routes_integrations.py's own module comment on
why this router is intentionally ungated).

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from control_center.main import app

client = TestClient(app)

_ALL_INTEGRATION_ENV_VARS = [
    "SENTRY_DSN", "SENTRY_API_TOKEN", "SENTRY_ORG", "SENTRY_PROJECT_SLUGS",
    "DISCORD_WEBHOOK_URL", "DISCORD_ALERT_WEBHOOK_URL",
]


def _clean_env(**overrides: str) -> dict:
    """Base environment with every integration var removed, then the
    given overrides applied -- so each test only asserts on the vars it
    actually cares about, unaffected by whatever happens to be set in
    the ambient test-runner environment."""
    env = dict(os.environ)
    for key in _ALL_INTEGRATION_ENV_VARS:
        env.pop(key, None)
    env.update(overrides)
    return env


class TestGetIntegrations(unittest.TestCase):
    """GET /integrations' env-var-driven configured/not-configured detection for Sentry
    and the two Discord webhooks, unauthenticated by design; one test checks that secret
    values set in the environment do not appear in the response body."""

    def test_returns_200_with_all_three_integrations(self) -> None:
        """The response always includes sentry/discord_notifications/
        discord_alerts keys."""
        with patch.dict(os.environ, _clean_env(), clear=True):
            resp = client.get("/integrations")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for key in ("sentry", "discord_notifications", "discord_alerts"):
            self.assertIn(key, data)

    def test_no_authentication_required(self) -> None:
        """GET /integrations is reachable without a token -- deliberate,
        not an oversight (same posture as GET /cloud)."""
        # Deliberate, not an oversight -- see routes_integrations.py's
        # module comment. Same posture as GET /cloud.
        with patch.dict(os.environ, _clean_env(), clear=True):
            resp = client.get("/integrations")
        self.assertNotEqual(resp.status_code, 401)
        self.assertNotEqual(resp.status_code, 403)

    def test_sentry_not_configured_without_dsn(self) -> None:
        """With SENTRY_DSN unset, sentry.configured is False."""
        with patch.dict(os.environ, _clean_env(), clear=True):
            data = client.get("/integrations").json()
        self.assertFalse(data["sentry"]["configured"])

    def test_sentry_configured_with_dsn(self) -> None:
        """With SENTRY_DSN set, sentry.configured is True."""
        with patch.dict(os.environ, _clean_env(SENTRY_DSN="https://key@sentry.io/123"), clear=True):
            data = client.get("/integrations").json()
        self.assertTrue(data["sentry"]["configured"])

    def test_sentry_report_aggregation_requires_all_three_vars(self) -> None:
        """report_aggregation_configured requires SENTRY_API_TOKEN AND
        SENTRY_ORG AND SENTRY_PROJECT_SLUGS together -- the token alone
        is not enough, mirroring scripts/sections/health.py's own gate."""
        # Token alone isn't enough -- mirrors scripts/sections/health.py's
        # own gate (token AND org AND project slugs).
        with patch.dict(os.environ, _clean_env(SENTRY_API_TOKEN="tok"), clear=True):
            data = client.get("/integrations").json()
        self.assertFalse(data["sentry"]["report_aggregation_configured"])

        with patch.dict(
            os.environ,
            _clean_env(SENTRY_API_TOKEN="tok", SENTRY_ORG="omnibioai", SENTRY_PROJECT_SLUGS="control-center"),
            clear=True,
        ):
            data = client.get("/integrations").json()
        self.assertTrue(data["sentry"]["report_aggregation_configured"])

    def test_discord_notifications_independent_of_alerts(self) -> None:
        """Setting only DISCORD_WEBHOOK_URL configures notifications but
        leaves discord_alerts unconfigured."""
        with patch.dict(os.environ, _clean_env(DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/x"), clear=True):
            data = client.get("/integrations").json()
        self.assertTrue(data["discord_notifications"]["configured"])
        self.assertFalse(data["discord_alerts"]["configured"])

    def test_discord_alerts_independent_of_notifications(self) -> None:
        """Setting only DISCORD_ALERT_WEBHOOK_URL configures alerts but
        leaves discord_notifications unconfigured."""
        with patch.dict(os.environ, _clean_env(DISCORD_ALERT_WEBHOOK_URL="https://discord.com/api/webhooks/y"), clear=True):
            data = client.get("/integrations").json()
        self.assertFalse(data["discord_notifications"]["configured"])
        self.assertTrue(data["discord_alerts"]["configured"])

    def test_response_never_contains_a_secret_value(self) -> None:
        """Defense-in-depth: with every secret env var set to a
        recognizable value, none of those raw values appear anywhere in
        the response body."""
        # Defense-in-depth: even if a future edit accidentally started
        # interpolating a credential into the response, this test fails
        # loudly rather than silently leaking it.
        secret_dsn = "https://supersecretkey@sentry.io/999"
        secret_token = "sentry-api-token-secret-value"
        secret_webhook = "https://discord.com/api/webhooks/999/supersecrettoken"
        with patch.dict(
            os.environ,
            _clean_env(
                SENTRY_DSN=secret_dsn,
                SENTRY_API_TOKEN=secret_token,
                SENTRY_ORG="omnibioai",
                SENTRY_PROJECT_SLUGS="control-center",
                DISCORD_WEBHOOK_URL=secret_webhook,
                DISCORD_ALERT_WEBHOOK_URL=secret_webhook,
            ),
            clear=True,
        ):
            resp = client.get("/integrations")
        raw_body = resp.text
        for secret in (secret_dsn, secret_token, secret_webhook):
            self.assertNotIn(secret, raw_body)

    def test_response_shape_is_booleans_and_static_strings_only(self) -> None:
        """Every integration entry has label/purpose/configured, and
        `configured` is always a real boolean."""
        with patch.dict(os.environ, _clean_env(), clear=True):
            data = client.get("/integrations").json()
        for entry in data.values():
            self.assertIn("label", entry)
            self.assertIn("purpose", entry)
            self.assertIn("configured", entry)
            self.assertIsInstance(entry["configured"], bool)


if __name__ == "__main__":
    unittest.main()
