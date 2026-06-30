from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx

DISCORD_COLORS = {
    'success': 0x00d4aa,
    'error':   0xe24b4a,
    'warning': 0xf59e0b,
    'info':    0x7c3aed,
}

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")


def notify(webhook_url: str, title: str, message: str,
           color: str = 'info', fields: dict | None = None) -> None:
    """Fire-and-forget Discord embed. Silently swallows all errors."""
    if not webhook_url:
        return
    embed: dict = {
        "title": title,
        "description": message,
        "color": DISCORD_COLORS.get(color, 0x7c3aed),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": "OmniBioAI Control Center"},
    }
    if fields:
        embed["fields"] = [
            {"name": k, "value": str(v), "inline": True}
            for k, v in fields.items()
        ]
    try:
        httpx.post(
            webhook_url,
            json={"username": "OmniBioAI", "embeds": [embed]},
            timeout=5,
        )
    except Exception as exc:
        print(f"Discord notify failed: {exc}")
