from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "publish_support_discord_event.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("support_discord_publisher", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_support_publisher_emits_only_fixed_unapproved_channel_payloads():
    for kind in ("incident", "resolved", "service-notice"):
        event = MODULE.build_envelope(kind, f"support:{kind}:0001", "2026-01-01T00:00:00+00:00")
        assert event["source_service"] == "support"
        assert event["destination_channel"] == "support"
        assert event["approved_publication"] is False
        assert event["event_id"] == event["correlation_id"]
        assert set(event["safe_message_payload"]) == {"title", "message", "color", "fields"}


def test_support_publisher_cannot_accept_ticket_content():
    event = MODULE.build_envelope("incident", "support:incident:0002", "2026-01-01T00:00:00+00:00")
    payload = str(event["safe_message_payload"]).lower()
    for sensitive in ("email", "ticket", "patient", "dataset", "filename", "prompt"):
        assert sensitive not in payload
