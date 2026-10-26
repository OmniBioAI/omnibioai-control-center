"""
tests/test_discord.py

Unit tests for:
  - control_center.notifications.discord.notify

notify() is a no-op without a webhook URL, posts a Discord embed with a
color keyed off DISCORD_COLORS (falling back to "info" for an unknown
key), turns a `fields` dict into inline embed fields, and never raises
even if the HTTP POST itself fails.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import unittest
import json
import os
from unittest.mock import patch

import httpx

from control_center.notifications import discord as discord_module


class TestNotify(unittest.TestCase):
    """notify()'s webhook-posting behavior: no-op without a URL, correct
    embed shape/color, and failure isolation."""

    def test_no_webhook_url_is_noop(self) -> None:
        """An empty webhook URL sends no HTTP request at all."""
        with patch.object(discord_module.httpx, "post") as mock_post:
            discord_module.notify("", "Title", "Message")
        mock_post.assert_not_called()

    def test_posts_embed_with_default_color(self) -> None:
        """A call with no `color` posts a single embed with the title/
        message and the "info" color, and no `fields` key at all."""
        with patch.dict(os.environ, {"DISCORD_LEGACY_WEBHOOK_FALLBACK": "enabled"}), \
                patch.object(discord_module.httpx, "post") as mock_post:
            discord_module.notify("https://discord.com/api/webhooks/123/test-token", "Title", "Message")

        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        payload = kwargs["json"]
        embed = payload["embeds"][0]
        self.assertEqual(embed["title"], "Title")
        self.assertEqual(embed["description"], "Message")
        self.assertEqual(embed["color"], discord_module.DISCORD_COLORS["info"])
        self.assertNotIn("fields", embed)

    def test_posts_embed_with_known_color(self) -> None:
        """A recognized `color` key (e.g. "error") sets the embed color
        to DISCORD_COLORS' matching value."""
        with patch.dict(os.environ, {"DISCORD_LEGACY_WEBHOOK_FALLBACK": "enabled"}), \
                patch.object(discord_module.httpx, "post") as mock_post:
            discord_module.notify(
                "https://discord.com/api/webhooks/123/test-token", "Title", "Message", color="error"
            )
        _, kwargs = mock_post.call_args
        embed = kwargs["json"]["embeds"][0]
        self.assertEqual(embed["color"], discord_module.DISCORD_COLORS["error"])

    def test_unknown_color_falls_back_to_info(self) -> None:
        """An unrecognized `color` string falls back to the "info" color
        rather than raising a KeyError."""
        with patch.dict(os.environ, {"DISCORD_LEGACY_WEBHOOK_FALLBACK": "enabled"}), \
                patch.object(discord_module.httpx, "post") as mock_post:
            discord_module.notify(
                "https://discord.com/api/webhooks/123/test-token", "Title", "Message", color="not-a-color"
            )
        _, kwargs = mock_post.call_args
        embed = kwargs["json"]["embeds"][0]
        self.assertEqual(embed["color"], discord_module.DISCORD_COLORS["info"])

    def test_fields_are_included_as_inline(self) -> None:
        """A `fields` dict is converted to a list of {name, value,
        inline: True} entries, in insertion order."""
        with patch.dict(os.environ, {"DISCORD_LEGACY_WEBHOOK_FALLBACK": "enabled"}), \
                patch.object(discord_module.httpx, "post") as mock_post:
            discord_module.notify(
                "https://discord.com/api/webhooks/123/test-token", "Title", "Message",
                fields={"Service": "svc-a", "Error": "timeout"},
            )
        _, kwargs = mock_post.call_args
        embed = kwargs["json"]["embeds"][0]
        self.assertEqual(
            embed["fields"],
            [
                {"name": "Service", "value": "svc-a", "inline": True},
                {"name": "Error", "value": "timeout", "inline": True},
            ],
        )

    def test_swallows_post_exception(self) -> None:
        """A failure raised by the underlying httpx.post call is swallowed
        -- notify() never propagates it to the caller."""
        with patch.dict(os.environ, {"DISCORD_LEGACY_WEBHOOK_FALLBACK": "enabled"}), \
                patch.object(discord_module.httpx, "post", side_effect=RuntimeError("boom")):
            # Should not raise.
            discord_module.notify("https://discord.com/api/webhooks/123/test-token", "Title", "Message")

    def test_non_2xx_response_is_logged_as_failure(self) -> None:
        response = httpx.Response(403, request=httpx.Request("POST", "https://discord.com/api/webhooks/123/test-token"))
        with patch.dict(os.environ, {"DISCORD_LEGACY_WEBHOOK_FALLBACK": "enabled"}), \
                patch.object(discord_module.httpx, "post", return_value=response):
            with self.assertLogs("control_center.notifications.discord", level="WARNING") as captured:
                discord_module.notify("https://discord.com/api/webhooks/123/test-token", "Title", "Message")
        self.assertIn("legacy Discord notify failed", captured.output[0])
        self.assertIn("403", captured.records[0].extra_fields["error"])

    def test_explicit_legacy_fallback_rejects_non_discord_target(self) -> None:
        with patch.dict(os.environ, {
            "DISCORD_EVENT_ROUTER_URL": "",
            "DISCORD_EVENT_INFRASTRUCTURE_SECRET": "",
            "DISCORD_LEGACY_WEBHOOK_FALLBACK": "enabled",
        }, clear=False), patch.object(discord_module.httpx, "post") as post:
            self.assertFalse(discord_module.notify("https://127.0.0.1/admin", "t", "m"))
        post.assert_not_called()

    def test_legacy_direct_fallback_is_disabled_by_default(self) -> None:
        env = {
            "DISCORD_EVENT_ROUTER_URL": "",
            "DISCORD_EVENT_INFRASTRUCTURE_SECRET": "",
            "DISCORD_LEGACY_WEBHOOK_FALLBACK": "",
        }
        with patch.dict(os.environ, env, clear=False), patch.object(discord_module.httpx, "post") as post:
            self.assertFalse(discord_module.notify("https://discord.com/api/webhooks/123/token", "t", "m"))
        post.assert_not_called()

    def test_enabled_legacy_fallback_without_webhook_is_a_noop(self) -> None:
        env = {
            "DISCORD_EVENT_ROUTER_URL": "",
            "DISCORD_EVENT_INFRASTRUCTURE_SECRET": "",
            "DISCORD_LEGACY_WEBHOOK_FALLBACK": "enabled",
        }
        with patch.dict(os.environ, env, clear=False), patch.object(discord_module.httpx, "post") as post:
            self.assertFalse(discord_module.notify("", "t", "m"))
        post.assert_not_called()

    def test_partial_router_configuration_fails_closed_even_with_fallback_opt_in(self) -> None:
        for env in (
            {"DISCORD_EVENT_ROUTER_URL": "https://control.example.test",
             "DISCORD_EVENT_INFRASTRUCTURE_SECRET": ""},
            {"DISCORD_EVENT_ROUTER_URL": "",
             "DISCORD_EVENT_INFRASTRUCTURE_SECRET": "synthetic-key"},
        ):
            with self.subTest(env=env), patch.dict(os.environ, {
                **env, "DISCORD_LEGACY_WEBHOOK_FALLBACK": "enabled",
            }, clear=False), patch.object(discord_module.httpx, "post") as post:
                self.assertFalse(discord_module.notify(
                    "https://discord.com/api/webhooks/123/token", "t", "m",
                ))
                post.assert_not_called()

    def test_central_alert_route_is_signed_sanitized_pending_and_never_falls_back(self) -> None:
        with patch.dict(os.environ, {
            "DISCORD_EVENT_ROUTER_URL": "https://control.example.test",
            "DISCORD_EVENT_INFRASTRUCTURE_SECRET": "s" * 43,
        }, clear=False), patch.object(discord_module.httpx, "post", return_value=httpx.Response(
            202, request=httpx.Request("POST", "https://control.example.test/integrations/discord/events")
        )) as post:
            result = discord_module.notify(
                "https://discord.com/api/webhooks/123/legacy-token", "private service", "internal detail",
                fields={"dataset": "private"}, event_id="runner:down:123",
            )
        self.assertTrue(result)
        self.assertEqual(post.call_count, 1)
        kwargs = post.call_args.kwargs
        envelope = json.loads(kwargs["content"])
        self.assertEqual(envelope["destination_channel"], "omnibioai-alerts")
        self.assertFalse(envelope["approved_publication"])
        self.assertNotIn("internal detail", kwargs["content"].decode())
        self.assertNotIn("private service", kwargs["content"].decode())
        self.assertNotIn("dataset", kwargs["content"].decode())
        self.assertEqual(kwargs["headers"]["X-Omni-Discord-Source"], "infrastructure")

    def test_central_alert_without_caller_id_generates_stable_fallback_identity(self) -> None:
        accepted = httpx.Response(
            202, request=httpx.Request("POST", "https://control.example.test/integrations/discord/events"),
        )
        with patch.dict(os.environ, {
            "DISCORD_EVENT_ROUTER_URL": "https://control.example.test",
            "DISCORD_EVENT_INFRASTRUCTURE_SECRET": "s" * 43,
        }, clear=False), patch.object(discord_module.httpx, "post", return_value=accepted) as post:
            self.assertTrue(discord_module.notify("legacy", "title", "message"))
        generated = json.loads(post.call_args.kwargs["content"])["event_id"]
        self.assertRegex(generated, r"^legacy-alert:\d+:[0-9a-f]{32}$")

    def test_central_alert_retry_uses_stable_id_and_never_dual_sends(self) -> None:
        rate_limited = httpx.Response(
            429, headers={"Retry-After": "0"},
            request=httpx.Request("POST", "https://control.example.test/integrations/discord/events"),
        )
        accepted = httpx.Response(
            202, request=httpx.Request("POST", "https://control.example.test/integrations/discord/events"),
        )
        with patch.dict(os.environ, {
            "DISCORD_EVENT_ROUTER_URL": "https://control.example.test",
            "DISCORD_EVENT_INFRASTRUCTURE_SECRET": "s" * 43,
        }, clear=False), patch.object(discord_module.httpx, "post", side_effect=[rate_limited, accepted]) as post, \
                patch.object(discord_module.time, "sleep") as sleep:
            self.assertTrue(discord_module.notify("legacy", "title", "message", event_id="stable:alert:1"))
        self.assertEqual(post.call_count, 2)
        self.assertEqual(json.loads(post.call_args_list[0].kwargs["content"])["event_id"], "stable:alert:1")
        self.assertEqual(json.loads(post.call_args_list[1].kwargs["content"])["event_id"], "stable:alert:1")
        sleep.assert_called_once_with(0.0)

    def test_central_permanent_rejection_does_not_send_legacy_webhook(self) -> None:
        rejected = httpx.Response(
            403, request=httpx.Request("POST", "https://control.example.test/integrations/discord/events"),
        )
        with patch.dict(os.environ, {
            "DISCORD_EVENT_ROUTER_URL": "https://control.example.test",
            "DISCORD_EVENT_INFRASTRUCTURE_SECRET": "s" * 43,
        }, clear=False), patch.object(discord_module.httpx, "post", return_value=rejected) as post:
            self.assertFalse(discord_module.notify("https://discord.com/api/webhooks/123/legacy", "t", "m", event_id="stable:alert:2"))
        self.assertEqual(post.call_count, 1)
        self.assertIn("control.example.test", post.call_args.args[0])

    def test_central_submission_fails_closed_for_invalid_configuration(self) -> None:
        for env, event_id in (
            ({"DISCORD_EVENT_ROUTER_URL": "https://control.example.test",
              "DISCORD_EVENT_INFRASTRUCTURE_SECRET": "short"}, "alert:1"),
            ({"DISCORD_EVENT_ROUTER_URL": "https://user:pass@evil.test/path",
              "DISCORD_EVENT_INFRASTRUCTURE_SECRET": "s" * 43}, "alert:2"),
            ({"DISCORD_EVENT_ROUTER_URL": "https://control.example.test",
              "DISCORD_EVENT_INFRASTRUCTURE_SECRET": "s" * 43}, "invalid id"),
        ):
            with patch.dict(os.environ, env, clear=False), patch.object(discord_module.httpx, "post") as post:
                self.assertFalse(discord_module.notify("legacy", "private", "details", event_id=event_id))
            post.assert_not_called()

    def test_central_submission_retries_server_errors_with_same_id(self) -> None:
        request = httpx.Request("POST", "https://control.example.test/integrations/discord/events")
        with patch.dict(os.environ, {
            "DISCORD_EVENT_ROUTER_URL": "https://control.example.test",
            "DISCORD_EVENT_INFRASTRUCTURE_SECRET": "s" * 43,
        }, clear=False), patch.object(discord_module.httpx, "post", side_effect=[
            httpx.Response(503, request=request), httpx.Response(503, request=request),
            httpx.Response(202, request=request),
        ]) as post, patch.object(discord_module.time, "sleep") as sleep:
            self.assertTrue(discord_module.notify("legacy", "title", "message", event_id="alert:stable"))
        self.assertEqual(post.call_count, 3)
        self.assertEqual(sleep.call_args_list, [unittest.mock.call(0.5), unittest.mock.call(1.0)])
        self.assertEqual({json.loads(call.kwargs["content"])["event_id"]
                          for call in post.call_args_list}, {"alert:stable"})

    def test_central_submission_retries_transport_failure_without_legacy_fallback(self) -> None:
        with patch.dict(os.environ, {
            "DISCORD_EVENT_ROUTER_URL": "https://control.example.test",
            "DISCORD_EVENT_INFRASTRUCTURE_SECRET": "s" * 43,
        }, clear=False), patch.object(
            discord_module.httpx, "post", side_effect=httpx.ConnectError("offline"),
        ) as post, patch.object(discord_module.time, "sleep") as sleep:
            self.assertFalse(discord_module.notify("legacy", "title", "message", event_id="alert:offline"))
        self.assertEqual(post.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_invalid_rate_limit_header_uses_bounded_backoff(self) -> None:
        response = httpx.Response(
            429, headers={"Retry-After": "invalid"},
            request=httpx.Request("POST", "https://control.example.test/integrations/discord/events"),
        )
        accepted = httpx.Response(
            202, request=httpx.Request("POST", "https://control.example.test/integrations/discord/events"),
        )
        with patch.dict(os.environ, {
            "DISCORD_EVENT_ROUTER_URL": "https://control.example.test",
            "DISCORD_EVENT_INFRASTRUCTURE_SECRET": "s" * 43,
        }, clear=False), patch.object(discord_module.httpx, "post", side_effect=[response, accepted]), \
                patch.object(discord_module.time, "sleep") as sleep:
            self.assertTrue(discord_module.notify("legacy", "title", "message", event_id="alert:429"))
        sleep.assert_called_once_with(0.5)

    def test_extreme_rate_limit_header_is_bounded(self) -> None:
        response = httpx.Response(
            429, headers={"Retry-After": "999999"},
            request=httpx.Request("POST", "https://control.example.test/integrations/discord/events"),
        )
        accepted = httpx.Response(
            202, request=httpx.Request("POST", "https://control.example.test/integrations/discord/events"),
        )
        with patch.dict(os.environ, {
            "DISCORD_EVENT_ROUTER_URL": "https://control.example.test",
            "DISCORD_EVENT_INFRASTRUCTURE_SECRET": "s" * 43,
        }, clear=False), patch.object(discord_module.httpx, "post", side_effect=[response, accepted]), \
                patch.object(discord_module.time, "sleep") as sleep:
            self.assertTrue(discord_module.notify("legacy", "title", "message", event_id="alert:bounded-429"))
        sleep.assert_called_once_with(4.0)

    def test_non_finite_rate_limit_header_uses_fallback(self) -> None:
        response = httpx.Response(
            429, headers={"Retry-After": "nan"},
            request=httpx.Request("POST", "https://control.example.test/integrations/discord/events"),
        )
        accepted = httpx.Response(
            202, request=httpx.Request("POST", "https://control.example.test/integrations/discord/events"),
        )
        with patch.dict(os.environ, {
            "DISCORD_EVENT_ROUTER_URL": "https://control.example.test",
            "DISCORD_EVENT_INFRASTRUCTURE_SECRET": "s" * 43,
        }, clear=False), patch.object(discord_module.httpx, "post", side_effect=[response, accepted]), \
                patch.object(discord_module.time, "sleep") as sleep:
            self.assertTrue(discord_module.notify("legacy", "title", "message", event_id="alert:nan-429"))
        sleep.assert_called_once_with(0.5)


if __name__ == "__main__":
    unittest.main()
