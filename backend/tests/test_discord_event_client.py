"""Tests for the standalone signed event-source client."""

from __future__ import annotations

import argparse
import http.server
import importlib.util
import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

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


def test_submit_signs_request_and_returns_safe_receipt(monkeypatch):
    monkeypatch.delenv(client.ACCESS_CLIENT_ID_ENV, raising=False)
    monkeypatch.delenv(client.ACCESS_CLIENT_SECRET_ENV, raising=False)

    class Response:
        status = 202
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps({"event_id": "docs:abc", "delivery_status": "pending_approval"}).encode()

    with patch.object(client._OPENER, "open", return_value=Response()) as opened:
        status, receipt = client.submit(
            client.build_envelope(args()), base_url="https://control.example.org", secret="x" * 43,
        )
    assert status == 202 and receipt["delivery_status"] == "pending_approval"
    request = opened.call_args.args[0]
    assert request.get_header("X-omni-discord-signature").startswith("v1=")
    assert "x" * 43 not in str(request.headers)
    assert request.get_header("Cf-access-client-id") is None
    assert request.get_header("Cf-access-client-secret") is None


SOURCE_SECRET = "s" * 43
ACCESS_ID, ACCESS_SECRET = "access-id-test-value", "access-secret-test-value"
EVENTS_PATH = "/integrations/discord/events"


class _Router(http.server.BaseHTTPRequestHandler):
    """Loopback router stub: replies from server.plan, records every request."""

    def _reply(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.server.seen.append((self.command, self.path, {k.lower(): v for k, v in self.headers.items()}))
        status, headers, body = self.server.plan[self.path]
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _reply

    def log_message(self, *_args):
        return None


@pytest.fixture
def router(monkeypatch):
    monkeypatch.delenv(client.ACCESS_CLIENT_ID_ENV, raising=False)
    monkeypatch.delenv(client.ACCESS_CLIENT_SECRET_ENV, raising=False)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Router)
    server.seen, server.plan = [], {}
    server.base_url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def _json(status, payload):
    return status, {"Content-Type": "application/json"}, json.dumps(payload).encode()


def _submit(router):
    return client.submit(client.build_envelope(args()), base_url=router.base_url, secret=SOURCE_SECRET)


def _assert_safe(message):
    for secret in (SOURCE_SECRET, ACCESS_ID, ACCESS_SECRET):
        assert secret not in message


def test_redirect_to_login_page_is_refused_and_never_followed(router):
    router.plan[EVENTS_PATH] = (302, {"Location": router.base_url + "/login"}, b"")
    router.plan["/login"] = (200, {"Content-Type": "text/html"}, b"<html>Sign in</html>")
    with pytest.raises(client.SubmissionError, match="redirect refused: HTTP 302") as exc:
        _submit(router)
    assert [path for _method, path, _headers in router.seen] == [EVENTS_PATH]
    _assert_safe(str(exc.value))


@pytest.mark.parametrize("reply, message", [
    ((200, {"Content-Type": "text/html"}, b"<html>Sign in</html>"), "not JSON"),
    (_json(202, {"delivery_status": "pending_approval"}), "does not match"),
    (_json(202, {"event_id": "docs:other"}), "does not match"),
    ((202, {"Content-Type": "application/json"}, b"not json"), "not valid JSON"),
    (_json(401, {"detail": "Discord event source authentication failed"}), "rejected the event: HTTP 401"),
])
def test_unaccepted_responses_fail_with_safe_message(router, reply, message):
    router.plan[EVENTS_PATH] = reply
    with pytest.raises(client.SubmissionError, match=message) as exc:
        _submit(router)
    _assert_safe(str(exc.value))


@pytest.mark.parametrize("status", [202, 200])
def test_queued_or_delivered_receipt_with_matching_event_id_succeeds(router, status):
    router.plan[EVENTS_PATH] = _json(status, {"event_id": "docs:abc", "delivery_status": "pending_approval"})
    assert _submit(router) == (status, {"event_id": "docs:abc", "delivery_status": "pending_approval"})


def test_access_headers_are_sent_only_when_both_are_set(router, monkeypatch):
    router.plan[EVENTS_PATH] = _json(202, {"event_id": "docs:abc"})
    _submit(router)
    monkeypatch.setenv(client.ACCESS_CLIENT_ID_ENV, ACCESS_ID)
    monkeypatch.setenv(client.ACCESS_CLIENT_SECRET_ENV, ACCESS_SECRET)
    _submit(router)
    (_, _, without), (_, _, with_access) = router.seen
    assert "cf-access-client-id" not in without and "cf-access-client-secret" not in without
    assert with_access["cf-access-client-id"] == ACCESS_ID
    assert with_access["cf-access-client-secret"] == ACCESS_SECRET


@pytest.mark.parametrize("name", [client.ACCESS_CLIENT_ID_ENV, client.ACCESS_CLIENT_SECRET_ENV])
def test_half_configured_access_fails_before_any_request(router, monkeypatch, name):
    monkeypatch.setenv(name, ACCESS_ID)
    with pytest.raises(client.SubmissionError, match="must be set together") as exc:
        _submit(router)
    assert router.seen == []
    _assert_safe(str(exc.value))


def test_cli_reports_unaccepted_response_without_secrets(router, monkeypatch, capsys):
    router.plan[EVENTS_PATH] = (200, {"Content-Type": "text/html"}, b"<html>Sign in</html>")
    monkeypatch.setenv("DISCORD_EVENT_ROUTER_URL", router.base_url)
    monkeypatch.setenv("DISCORD_EVENT_SOURCE_SECRET", SOURCE_SECRET)
    monkeypatch.setattr(client.sys, "argv", [
        "publish_discord_event.py", "--event-id", "docs:abc", "--event-type", "documentation.published",
        "--source", "documentation", "--title", "t", "--message", "m", "--correlation-id", "docs:abc",
    ])
    assert client.main() == 1
    err = capsys.readouterr().err
    assert "router response is not JSON (HTTP 200)" in err
    _assert_safe(err)


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
