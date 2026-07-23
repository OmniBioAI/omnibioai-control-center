"""
tests/test_discord.py

Unit tests for:
  - control_center.notifications.discord.notify
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from control_center.notifications import discord as discord_module


class TestNotify(unittest.TestCase):

    def test_no_webhook_url_is_noop(self) -> None:
        with patch.object(discord_module.httpx, "post") as mock_post:
            discord_module.notify("", "Title", "Message")
        mock_post.assert_not_called()

    def test_posts_embed_with_default_color(self) -> None:
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
        with patch.object(discord_module.httpx, "post") as mock_post:
            discord_module.notify(
                "https://discord.example/webhook", "Title", "Message", color="error"
            )
        _, kwargs = mock_post.call_args
        embed = kwargs["json"]["embeds"][0]
        self.assertEqual(embed["color"], discord_module.DISCORD_COLORS["error"])

    def test_unknown_color_falls_back_to_info(self) -> None:
        with patch.object(discord_module.httpx, "post") as mock_post:
            discord_module.notify(
                "https://discord.example/webhook", "Title", "Message", color="not-a-color"
            )
        _, kwargs = mock_post.call_args
        embed = kwargs["json"]["embeds"][0]
        self.assertEqual(embed["color"], discord_module.DISCORD_COLORS["info"])

    def test_fields_are_included_as_inline(self) -> None:
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
        with patch.object(discord_module.httpx, "post", side_effect=RuntimeError("boom")):
            # Should not raise.
            discord_module.notify("https://discord.example/webhook", "Title", "Message")


if __name__ == "__main__":
    unittest.main()
