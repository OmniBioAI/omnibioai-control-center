"""Tests for the standalone signed event-source client."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

from control_center.notifications.discord import EVENT_ROUTES
from control_center.notifications.discord_events import SOURCE_EVENT_TYPES


SCRIPT = Path(__file__).parents[2] / "scripts" / "publish_discord_event.py"
SPEC = importlib.util.spec_from_file_location("publish_discord_event", SCRIPT)
client = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(client)


def args(**changes):
    values = dict(
        event_id="docs:abc", event_type="documentation.published", source="documentation",
        title="Docs published", message="Public docs are available.",
        correlation_id="docs:abc", color="success", fields_json='{"Version":"abc"}', approved=True,
    )
    values.update(changes)
    return argparse.Namespace(**values)


def test_build_envelope_sets_exact_destination_and_metadata():
    result = client.build_envelope(args())
    assert result["destination_channel"] == "tutorials"
    assert result["approved_publication"] is True
    assert result["safe_message_payload"]["fields"] == {"Version": "abc"}


def test_submit_rejects_unsafe_router_url_without_network():
    for url in ("http://public.example", "https://user:pass@example.org", "file:///tmp/socket"):
        try:
            client.submit(client.build_envelope(args()), base_url=url, secret="x" * 43)
        except ValueError:
            pass
        else:
            raise AssertionError(url)


def test_submit_signs_request_and_returns_safe_receipt():
    class Response:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps({"event_id": "docs:abc", "delivery_status": "pending_approval"}).encode()

    with patch.object(client.urllib.request, "urlopen", return_value=Response()) as opened:
        status, receipt = client.submit(
            client.build_envelope(args()), base_url="https://control.example.org", secret="x" * 43,
        )
    assert status == 202 and receipt["delivery_status"] == "pending_approval"
    request = opened.call_args.args[0]
    assert request.get_header("X-omni-discord-signature").startswith("v1=")
    assert "x" * 43 not in str(request.headers)


def test_all_seven_source_contracts_are_present_and_reject_cross_source_events():
    assert set(client.SOURCE_EVENT_TYPES) == {
        "github", "rag", "workbench", "documentation", "video", "infrastructure", "support",
    }
    assert all(client.SOURCE_EVENT_TYPES[source] for source in client.SOURCE_EVENT_TYPES)
    try:
        client.build_envelope(args(source="video", event_type="platform.release"))
    except ValueError as exc:
        assert "not authorized" in str(exc)
    else:
        raise AssertionError("cross-source event type was accepted")


def test_standalone_client_matches_authoritative_router_inventory_exactly():
    """Prevent copied CLI contracts from inventing identities or event scopes."""
    assert client.ROUTES == EVENT_ROUTES
    assert client.SOURCE_EVENT_TYPES == {
        source: set(event_types) for source, event_types in SOURCE_EVENT_TYPES.items()
    }


def test_every_authorized_source_event_pair_has_a_central_destination():
    for source, event_types in client.SOURCE_EVENT_TYPES.items():
        for event_type in event_types:
            envelope = client.build_envelope(args(source=source, event_type=event_type))
            assert envelope["destination_channel"] == client.ROUTES[event_type]
