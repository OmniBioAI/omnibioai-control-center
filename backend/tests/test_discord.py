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
from unittest.mock import patch

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
        with patch.object(discord_module.httpx, "post") as mock_post:
            discord_module.notify("https://discord.example/webhook", "Title", "Message")

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
        with patch.object(discord_module.httpx, "post") as mock_post:
            discord_module.notify(
                "https://discord.example/webhook", "Title", "Message", color="error"
            )
        _, kwargs = mock_post.call_args
        embed = kwargs["json"]["embeds"][0]
        self.assertEqual(embed["color"], discord_module.DISCORD_COLORS["error"])

    def test_unknown_color_falls_back_to_info(self) -> None:
        """An unrecognized `color` string falls back to the "info" color
        rather than raising a KeyError."""
        with patch.object(discord_module.httpx, "post") as mock_post:
            discord_module.notify(
                "https://discord.example/webhook", "Title", "Message", color="not-a-color"
            )
        _, kwargs = mock_post.call_args
        embed = kwargs["json"]["embeds"][0]
        self.assertEqual(embed["color"], discord_module.DISCORD_COLORS["info"])

    def test_fields_are_included_as_inline(self) -> None:
        """A `fields` dict is converted to a list of {name, value,
        inline: True} entries, in insertion order."""
        with patch.object(discord_module.httpx, "post") as mock_post:
            discord_module.notify(
                "https://discord.example/webhook", "Title", "Message",
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
        with patch.object(discord_module.httpx, "post", side_effect=RuntimeError("boom")):
            # Should not raise.
            discord_module.notify("https://discord.example/webhook", "Title", "Message")


if __name__ == "__main__":
    unittest.main()
