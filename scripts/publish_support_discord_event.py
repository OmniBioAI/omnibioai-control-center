#!/usr/bin/env python3
"""Operator-triggered, fixed-template support event for the central router.

This is intentionally not connected to a ticket database: no authoritative
support system exists in this ecosystem checkout. Operators may submit only
after confirming the incident is public and sanitized. The event remains
unapproved in Control Center and requires its normal IAM approval before send.
"""
from __future__ import annotations

import argparse
import os
import sys

from publish_discord_event import submit

EVENTS = {
    "incident": ("support.incident", "Public support incident", "An operator submitted a public support incident for review.", "warning"),
    "resolved": ("support.resolved", "Support incident resolved", "An operator submitted a public support recovery notice for review.", "success"),
    "service-notice": ("support.incident", "Public service notice", "An operator submitted a public service notice for review.", "info"),
}


def build_envelope(kind: str, event_id: str, created_at: str) -> dict:
    event_type, title, message, color = EVENTS[kind]
    return {
        "event_id": event_id, "event_type": event_type,
        "source_service": "support", "created_at": created_at,
        "destination_channel": "support", "approved_publication": False,
        "safe_message_payload": {"title": title, "message": message, "color": color, "fields": {}},
        "correlation_id": event_id,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=sorted(EVENTS), required=True)
    parser.add_argument("--event-id", required=True, help="Stable, non-sensitive operator reference")
    parser.add_argument("--publicly-reviewed", action="store_true", help="Attest that no ticket/PII/sensitive detail is included")
    args = parser.parse_args()
    if not args.publicly_reviewed:
        parser.error("--publicly-reviewed is required; event will still require Control Center approval")
    if not args.event_id or len(args.event_id) > 200 or not args.event_id.replace("-", "").replace("_", "").replace(":", "").replace(".", "").isalnum():
        parser.error("--event-id must be a stable non-sensitive identifier")
    base = os.environ.get("DISCORD_EVENT_ROUTER_URL", "").strip()
    secret = os.environ.get("DISCORD_EVENT_SUPPORT_SECRET", "")
    if not base or not secret:
        print("support Discord source configuration is unavailable", file=sys.stderr)
        return 2
    # submit() expects its regular envelope timestamp to be supplied by the
    # common schema builder. Use the shared stable transport helper without
    # accepting any caller-controlled message content.
    from datetime import datetime, timezone
    envelope = build_envelope(args.kind, args.event_id, datetime.now(timezone.utc).isoformat())
    try:
        status, receipt = submit(envelope, base_url=base, secret=secret)
    except (ValueError, OSError) as exc:
        print(f"support event submission failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    if status not in {200, 202}:
        print(f"support event submission rejected: HTTP {status}", file=sys.stderr)
        return 1
    print(f"support event accepted for review: {receipt.get('event_id', args.event_id)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
