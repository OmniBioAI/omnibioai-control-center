#!/usr/bin/env python3
"""Submit one signed, schema-valid event to the central Discord router.

This client never receives a webhook URL. It exits 2 when central routing is
not configured (allowing explicitly documented legacy fallbacks), 1 on a
rejected/failed request, and 0 when the router durably accepts the event.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# Statuses the router's ingest handler returns for accepted or duplicate
# events (routes_discord_events.py): 200 once delivered, 202 otherwise.
ACCEPTED_STATUSES = frozenset({200, 202})
ACCESS_CLIENT_ID_ENV = "DISCORD_EVENT_ACCESS_CLIENT_ID"
ACCESS_CLIENT_SECRET_ENV = "DISCORD_EVENT_ACCESS_CLIENT_SECRET"
# Cloudflare bans urllib's default "Python-urllib/x.y" signature (error 1010)
# at the edge, before Access or the router see the request.
USER_AGENT = "omnibioai-discord-publisher/1.0"

ROUTES = {
    "platform.release": "announcements", "platform.milestone": "announcements",
    "github.issue.confirmed": "bug-reports", "github.issue.resolved": "bug-reports",
    "feature.request.accepted": "feature-requests", "support.incident": "support",
    "support.resolved": "support", "documentation.published": "tutorials",
    "video.published": "tutorials", "infrastructure.alert": "omnibioai-alerts",
    "security.alert": "omnibioai-alerts",
    "github.workflow.failed": "omnibioai-alerts",
}
SOURCE_EVENT_TYPES = {
    "github": {"platform.release", "platform.milestone", "github.issue.confirmed", "github.issue.resolved", "feature.request.accepted", "github.workflow.failed"},
    "rag": {"support.incident", "support.resolved", "documentation.published"},
    "workbench": {"support.incident", "support.resolved", "platform.release"},
    "documentation": {"documentation.published", "infrastructure.alert"},
    "video": {"video.published"},
    "infrastructure": {"infrastructure.alert", "security.alert"},
    "support": {"support.incident", "support.resolved", "feature.request.accepted"},
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--event-type", choices=sorted(ROUTES), required=True)
    parser.add_argument("--source", choices=sorted(SOURCE_EVENT_TYPES), required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--correlation-id", required=True)
    parser.add_argument("--color", choices=("info", "success", "warning", "error"), default="info")
    parser.add_argument("--fields-json", default="{}")
    parser.add_argument("--approved", action="store_true")
    return parser


def build_envelope(args: argparse.Namespace) -> dict:
    if args.event_type not in SOURCE_EVENT_TYPES.get(args.source, set()):
        raise ValueError("event type is not authorized for this source")
    fields = json.loads(args.fields_json)
    if not isinstance(fields, dict):
        raise ValueError("fields-json must contain an object")
    return {
        "event_id": args.event_id,
        "event_type": args.event_type,
        "source_service": args.source,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "destination_channel": ROUTES[args.event_type],
        "approved_publication": bool(args.approved),
        "safe_message_payload": {
            "title": args.title, "message": args.message,
            "color": args.color, "fields": fields,
        },
        "correlation_id": args.correlation_id,
    }


class SubmissionError(ValueError):
    """The router did not durably accept the event.

    Messages are fixed text plus an HTTP status; they never include response
    bodies, URLs or credentials.
    """


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so an Access login page can never count as accepted."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


def _access_headers() -> dict[str, str]:
    client_id = os.environ.get(ACCESS_CLIENT_ID_ENV, "").strip()
    client_secret = os.environ.get(ACCESS_CLIENT_SECRET_ENV, "").strip()
    if not client_id and not client_secret:
        return {}
    if not client_id or not client_secret:
        raise SubmissionError(f"{ACCESS_CLIENT_ID_ENV} and {ACCESS_CLIENT_SECRET_ENV} must be set together")
    return {"CF-Access-Client-Id": client_id, "CF-Access-Client-Secret": client_secret}


def check_receipt(status: int, content_type: str, raw: bytes, event_id: str) -> dict:
    """The single success rule for every caller of submit()."""
    if status not in ACCEPTED_STATUSES:
        raise SubmissionError(f"router did not accept the event: HTTP {status}")
    if content_type.split(";", 1)[0].strip().lower() != "application/json":
        raise SubmissionError(f"router response is not JSON (HTTP {status})")
    try:
        receipt = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SubmissionError(f"router response is not valid JSON (HTTP {status})") from None
    if not isinstance(receipt, dict) or receipt.get("event_id") != event_id:
        raise SubmissionError(f"router receipt does not match the submitted event (HTTP {status})")
    return receipt


def submit(envelope: dict, *, base_url: str, secret: str, timeout: float = 8.0) -> tuple[int, dict]:
    """Return (status, receipt) only when check_receipt() accepts the response."""
    if len(secret) < 43 or not secret.isascii() or not secret.replace("-", "").replace("_", "").isalnum():
        raise ValueError("DISCORD_EVENT_SOURCE_SECRET is invalid")
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme not in {"https", "http"} or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("DISCORD_EVENT_ROUTER_URL is invalid")
    if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost", "control-center"}:
        raise ValueError("DISCORD_EVENT_ROUTER_URL must use HTTPS outside the local service network")
    body = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    nonce = secrets.token_urlsafe(18)
    signed = timestamp.encode() + b"\n" + nonce.encode() + b"\n" + body
    signature = "v1=" + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    url = base_url.rstrip("/") + "/integrations/discord/events"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "X-Omni-Discord-Source": envelope["source_service"],
        "X-Omni-Discord-Timestamp": timestamp,
        "X-Omni-Discord-Nonce": nonce,
        "X-Omni-Discord-Signature": signature,
    }
    headers.update(_access_headers())
    request = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            status, content_type, raw = response.status, response.headers.get("Content-Type", ""), response.read()
    except urllib.error.HTTPError as exc:
        # Do not echo response bodies: upstream errors may contain internal data.
        if 300 <= exc.code < 400:
            raise SubmissionError(f"router redirect refused: HTTP {exc.code}") from None
        raise SubmissionError(f"router rejected the event: HTTP {exc.code}") from None
    return status, check_receipt(status, content_type, raw, envelope["event_id"])


def main() -> int:
    args = _parser().parse_args()
    base_url = os.environ.get("DISCORD_EVENT_ROUTER_URL", "").strip()
    secret = os.environ.get("DISCORD_EVENT_SOURCE_SECRET", "")
    if not base_url or len(secret) < 43 or not secret.isascii() or not secret.replace("-", "").replace("_", "").isalnum():
        print("central Discord event routing is not configured", file=sys.stderr)
        return 2
    try:
        status, receipt = submit(build_envelope(args), base_url=base_url, secret=secret)
    except SubmissionError as exc:
        print(f"Discord event submission failed: {exc}", file=sys.stderr)
        return 1
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        print(f"Discord event submission failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps({
        "event_id": receipt.get("event_id", args.event_id),
        "delivery_status": receipt.get("delivery_status", "accepted"),
        "destination_channel": receipt.get("destination_channel", ROUTES[args.event_type]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
