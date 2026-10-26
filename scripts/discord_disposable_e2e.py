#!/usr/bin/env python3
"""Exercise a disposable authenticated event→approval→mock delivery flow.

This has no external network, production database, credentials, or live
Discord dependency. API/IAM authorization is covered by route tests, not this
in-process pipeline check.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from unittest.mock import patch

from control_center.notifications.discord import AUTOMATED_CHANNELS, COMMUNITY_CHANNELS, EVENT_ROUTES, DiscordPublisher
from control_center.notifications.discord_events import (
    DiscordEventStore,
    parse_event_payload,
    sign_request,
    verify_request_signature,
)


def main() -> int:
    secret = "A" * 43
    events = [
        ("github", "platform.release", "announcements"),
        ("github", "github.issue.confirmed", "bug-reports"),
        ("support", "feature.request.accepted", "feature-requests"),
        ("support", "support.incident", "support"),
        ("documentation", "documentation.published", "tutorials"),
        ("infrastructure", "infrastructure.alert", "omnibioai-alerts"),
    ]
    webhooks = {
        channel: f"https://discord.com/api/webhooks/{10000 + index}/disposable-token"
        for index, channel in enumerate(sorted(AUTOMATED_CHANNELS))
    }
    calls: list[tuple[str, dict]] = []

    class MockDiscordResponse:
        status_code = 204
        headers = {}

    def mock_discord(url: str, **kwargs):
        calls.append((url, kwargs["json"]))
        return MockDiscordResponse()

    with tempfile.TemporaryDirectory(prefix="omnibio-discord-e2e-") as state_dir:
        store = DiscordEventStore(state_dir)
        publisher = DiscordPublisher(webhooks, state_dir=state_dir, post=mock_discord, sleep=lambda _: None)
        with patch("control_center.notifications.discord.httpx.post", side_effect=mock_discord):
            delivered_channels = []
            for index, (source, event_type, channel) in enumerate(events):
                event_id = f"e2e:{channel}:0001"
                timestamp = str(int(time.time()))
                nonce = f"disposable-nonce-{index:04d}"
                body = json.dumps({
                    "event_id": event_id, "event_type": event_type,
                    "source_service": source, "created_at": datetime.now(timezone.utc).isoformat(),
                    "destination_channel": channel, "approved_publication": False,
                    "safe_message_payload": {
                        "title": "DISPOSABLE INTEGRATION TEST",
                        "message": f"Synthetic {channel} event; this is not a public notice.",
                        "color": "info", "fields": {},
                    }, "correlation_id": event_id,
                }, separators=(",", ":")).encode()
                signature = sign_request(secret, timestamp, nonce, body)
                verify_request_signature(
                    source=source, timestamp=timestamp, nonce=nonce,
                    signature=signature, body=body, secrets={source: secret},
                )
                event, envelope = parse_event_payload(body, authenticated_source=source)
                record, duplicate = store.ingest(event, envelope)
                assert not duplicate and record["delivery_status"] == "pending_approval"
                assert record["approval_state"] == "pending"
                approved_record = store.approve(event_id, "disposable-test-operator")
                approved_event = store.event_from_record(approved_record)
                assert approved_record["approval_state"] == "approved" and approved_event.approved
                first = publisher.publish(approved_event)
                assert first.status == "delivered" and first.channel == channel
                assert publisher.delivery_state(event_id)[0] == "delivered"
                assert publisher.publish(approved_event).status == "duplicate"
                assert store.ingest(event, envelope)[1] is True
                delivered_channels.append(channel)

        assert len(calls) == len(events)
        assert set(delivered_channels) == AUTOMATED_CHANNELS
        assert not AUTOMATED_CHANNELS.intersection({"general", "research-chat", "show-and-tell"})
        assert all(channel in AUTOMATED_CHANNELS for channel in delivered_channels)
        assert all(calls[i][1]["allowed_mentions"]["parse"] == [] for i in range(len(calls)))

    print("disposable_e2e=PASS routes=6/6 community_exclusions=3/3 signature=PASS durable_approval=PASS mock_delivery=PASS duplicate_suppression=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
