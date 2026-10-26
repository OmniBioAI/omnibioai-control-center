"""Isolated tests for secure, event-driven Discord routing."""

from __future__ import annotations

import json
import os
import time
from contextlib import closing
from dataclasses import dataclass, field

import pytest
import httpx

from control_center.notifications.discord import (
    COMMUNITY_CHANNELS,
    EVENT_ROUTES,
    DiscordConfigError,
    DiscordEvent,
    DiscordPublisher,
    _validate_distinct_webhooks,
    _redact,
    channel_configuration_status,
    load_channel_webhooks,
)
from control_center.notifications.discord_events import SOURCE_EVENT_TYPES


def webhook(channel: str) -> str:
    number = str(abs(hash(channel)) % 900000 + 100000)
    return f"https://discord.com/api/webhooks/{number}/test-token-{channel}"


@dataclass
class Response:
    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    body: dict = field(default_factory=dict)

    def json(self):
        return self.body


def event(event_type: str, suffix: str = "1", **kwargs) -> DiscordEvent:
    title = kwargs.pop("title", "Approved update")
    message = kwargs.pop("message", "Public content")
    return DiscordEvent(
        event_id=f"{event_type}:{suffix}",
        event_type=event_type,
        title=title,
        message=message,
        approved=True,
        **kwargs,
    )


def test_every_event_routes_once_without_cross_channel_leakage(tmp_path):
    calls = []
    urls = {channel: webhook(channel) for channel in set(EVENT_ROUTES.values())}

    def post(url, **kwargs):
        calls.append((url, kwargs["json"]))
        return Response(204)

    publisher = DiscordPublisher(urls, state_dir=tmp_path, post=post, sleep=lambda _: None)
    for index, (event_type, expected_channel) in enumerate(EVENT_ROUTES.items()):
        result = publisher.publish(event(event_type, str(index)))
        assert result.status == "delivered"
        assert result.channel == expected_channel
        assert calls[-1][0] == urls[expected_channel]
    assert len(calls) == len(EVENT_ROUTES)


def test_route_inventory_covers_channels_and_sources_without_community_automation():
    automated = {
        "announcements", "bug-reports", "feature-requests", "support",
        "tutorials", "omnibioai-alerts",
    }
    community_only = {"general", "research-chat", "show-and-tell"}
    authorized_pairs = {
        (source, event_type)
        for source, event_types in SOURCE_EVENT_TYPES.items()
        for event_type in event_types
    }

    assert set(EVENT_ROUTES.values()) == automated
    assert not set(EVENT_ROUTES.values()) & community_only
    assert all(any(event_type == routed for _, routed in authorized_pairs) for event_type in EVENT_ROUTES)
    assert all(
        any(EVENT_ROUTES[event_type] == channel for _, event_type in authorized_pairs)
        for channel in automated
    )
    assert set(SOURCE_EVENT_TYPES) == {
        "github", "rag", "workbench", "documentation", "video", "infrastructure", "support",
    }
    assert all(event_types for event_types in SOURCE_EVENT_TYPES.values())


def test_all_nine_channels_have_explicit_configuration_status():
    status = channel_configuration_status({"DISCORD_ALERT_WEBHOOK_URL": webhook("alerts")})
    assert set(status) == set(COMMUNITY_CHANNELS)
    assert status["omnibioai-alerts"] == "configured"
    assert status["general"] == "community-driven"
    assert status["announcements"] == "missing"


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        "[]",
        json.dumps({"announcements": "http://discord.com/api/webhooks/1/token"}),
        json.dumps({"announcements": "https://discord.com:8443/api/webhooks/1/token"}),
        json.dumps({"announcements": "https://discord.com:invalid/api/webhooks/1/token"}),
        json.dumps({"announcements": "https://evil.example/api/webhooks/1/token"}),
        json.dumps({"general": webhook("general")}),
        json.dumps({"unknown": webhook("unknown")}),
        json.dumps({"support": ""}),
    ],
)
def test_invalid_channel_configuration_is_rejected_without_echoing_secret(raw):
    with pytest.raises(DiscordConfigError) as caught:
        load_channel_webhooks({"DISCORD_CHANNEL_WEBHOOKS": raw})
    assert "test-token" not in str(caught.value)


def test_missing_webhook_is_reported_without_delivery(tmp_path):
    publisher = DiscordPublisher({}, state_dir=tmp_path, post=lambda *_a, **_k: pytest.fail("posted"))
    result = publisher.publish(event("support.incident"))
    assert result.status == "not_configured"
    assert result.channel == "support"


def test_publisher_from_env_uses_configured_private_state_dir(tmp_path):
    channel_map = json.dumps({"announcements": webhook("announcements")})
    publisher = DiscordPublisher.from_env({
        "DISCORD_CHANNEL_WEBHOOKS": channel_map,
        "DISCORD_DELIVERY_STATE_DIR": str(tmp_path / "private-state"),
    })
    assert publisher.db_path == tmp_path / "private-state" / "deliveries.sqlite3"
    assert os.stat(publisher.state_dir).st_mode & 0o777 == 0o700


def test_recent_pending_claim_remains_owned_by_first_worker(tmp_path):
    publisher = DiscordPublisher({"support": webhook("support")}, state_dir=tmp_path)
    item = event("support.incident", "live-claim")
    assert publisher._claim(item, "support")
    assert not publisher._claim(item, "support")


@pytest.mark.parametrize("attempts", [0, 9])
def test_invalid_retry_bounds_are_rejected(tmp_path, attempts):
    with pytest.raises(DiscordConfigError, match="max_attempts"):
        DiscordPublisher({}, state_dir=tmp_path, max_attempts=attempts)


def test_unknown_automated_webhook_key_is_rejected(tmp_path):
    with pytest.raises(DiscordConfigError, match="unroutable"):
        DiscordPublisher({"general": webhook("general")}, state_dir=tmp_path)


def test_channel_map_rejects_duplicate_webhook_destination_without_echoing_secret():
    raw = json.dumps({
        "announcements": "https://discord.com/api/webhooks/123/secret-one",
        "support": "https://discord.com/api/webhooks/123/secret-two",
    })
    with pytest.raises(DiscordConfigError, match="same webhook destination") as caught:
        load_channel_webhooks({"DISCORD_CHANNEL_WEBHOOKS": raw})
    assert "secret-one" not in str(caught.value)
    assert "secret-two" not in str(caught.value)


def test_direct_publisher_rejects_duplicate_webhook_destination(tmp_path):
    with pytest.raises(DiscordConfigError, match="same webhook destination"):
        DiscordPublisher({
            "announcements": "https://discord.com/api/webhooks/123/secret-one",
            "support": "https://discord.com/api/webhooks/123/secret-two",
        }, state_dir=tmp_path)


def test_distinct_webhook_defense_rejects_unvalidated_paths():
    with pytest.raises(DiscordConfigError, match="invalid Discord webhook configuration"):
        _validate_distinct_webhooks({"support": "https://discord.com/not-a-webhook"})


def test_legacy_alert_credential_cannot_alias_another_channel_when_overridden():
    with pytest.raises(DiscordConfigError, match="legacy alerts webhook aliases"):
        load_channel_webhooks({
            "DISCORD_CHANNEL_WEBHOOKS": json.dumps({
                "omnibioai-alerts": "https://discord.com/api/webhooks/456/new-alert-token",
                "support": "https://discord.com/api/webhooks/123/support-token",
            }),
            "DISCORD_ALERT_WEBHOOK_URL": "https://discord.com/api/webhooks/123/legacy-alert-token",
        })


def test_event_destination_and_identity_are_validated(tmp_path):
    publisher = DiscordPublisher({"support": webhook("support")}, state_dir=tmp_path)
    with pytest.raises(ValueError, match="destination_channel"):
        publisher.publish(event("support.incident", destination_channel="announcements"))
    invalid_id = event("support.incident")
    invalid_id = DiscordEvent(**{**invalid_id.__dict__, "event_id": "bad id"})
    with pytest.raises(ValueError, match="event_id"):
        publisher.publish(invalid_id)


def test_pending_delivery_is_marked_unknown_and_requires_explicit_replay(tmp_path):
    publisher = DiscordPublisher({"support": webhook("support")}, state_dir=tmp_path)
    item = event("support.incident", "pending")
    assert publisher._claim(item, "support")
    # A recent pending record is owned by another worker; after the lease
    # expires it is ambiguous and must not be automatically reclaimed.
    with closing(publisher._connect()) as connection, connection:
        connection.execute(
            "UPDATE discord_deliveries SET updated_at=? WHERE event_id=?",
            (time.time() - 301, item.event_id),
        )
    assert not publisher._claim(item, "support")
    with closing(publisher._connect()) as connection, connection:
        state = connection.execute(
            "SELECT status FROM discord_deliveries WHERE event_id=?", (item.event_id,),
        ).fetchone()[0]
    assert state == "unknown"
    assert not publisher._claim(item, "support")
    assert publisher._claim(item, "support", replay=True)


@pytest.mark.parametrize(
    ("headers", "body", "expected"),
    [({"Retry-After": "bad"}, {"retry_after": 2.25}, 2.25), ({}, {}, 0.5),
     ({"Retry-After": "100"}, {}, 8.0), ({"Retry-After": "nan"}, {}, 0.5)],
)
def test_retry_delay_falls_back_to_json_or_bounded_backoff(tmp_path, headers, body, expected):
    publisher = DiscordPublisher(
        {}, state_dir=tmp_path, base_backoff=0.5, max_backoff=8,
    )
    assert publisher._retry_delay(Response(429, headers, body), 1) == expected


@pytest.mark.parametrize("status", [401, 403])
def test_missing_or_revoked_webhook_permission_dead_letters_without_retry(tmp_path, status):
    sleeps = []
    publisher = DiscordPublisher(
        {"support": webhook("support")}, state_dir=tmp_path,
        post=lambda *_a, **_k: Response(status), sleep=sleeps.append,
    )
    result = publisher.publish(event("support.incident", str(status)))
    assert result.status == "failed"
    assert result.attempts == 1
    assert sleeps == []
    record = json.loads(publisher.dlq_path.read_text().strip())
    assert record["channel"] == "support"
    assert "title" not in record and "message" not in record
    assert oct(os.stat(publisher.dlq_path).st_mode & 0o777) == "0o600"


def test_rate_limit_honors_retry_after_and_then_succeeds(tmp_path):
    responses = iter([Response(429, {"Retry-After": "1.25"}), Response(204)])
    sleeps = []
    publisher = DiscordPublisher(
        {"tutorials": webhook("tutorials")}, state_dir=tmp_path,
        post=lambda *_a, **_k: next(responses), sleep=sleeps.append,
    )
    result = publisher.publish(event("video.published"))
    assert result.status == "delivered" and result.attempts == 2
    assert sleeps == [1.25]


def test_5xx_is_ambiguous_and_not_blindly_retried(tmp_path):
    sleeps = []
    publisher = DiscordPublisher(
        {"announcements": webhook("announcements")}, state_dir=tmp_path,
        max_attempts=4, base_backoff=0.5,
        post=lambda *_a, **_k: Response(503), sleep=sleeps.append,
    )
    result = publisher.publish(event("platform.release"))
    assert result.status == "delivery_unknown" and result.attempts == 1
    assert sleeps == []
    record = json.loads(publisher.dlq_path.read_text().strip())
    assert record["error"] == "Discord returned HTTP 503"


def test_failure_on_one_channel_does_not_block_unrelated_channel(tmp_path):
    urls = {
        "support": webhook("support"),
        "announcements": webhook("announcements"),
    }
    calls = []

    def post(url, **_kwargs):
        calls.append(url)
        return Response(503 if url == urls["support"] else 204)

    publisher = DiscordPublisher(urls, state_dir=tmp_path, post=post)
    failed = publisher.publish(event("support.incident", "independent-failure"))
    passed = publisher.publish(event("platform.release", "independent-success"))

    assert failed.status == "delivery_unknown"
    assert passed.status == "delivered"
    assert calls == [urls["support"], urls["announcements"]]


def test_read_timeout_is_ambiguous_but_connect_error_can_retry(tmp_path):
    result = DiscordPublisher(
        {"support": webhook("support")}, state_dir=tmp_path / "read-timeout",
        post=lambda *_a, **_k: (_ for _ in ()).throw(httpx.ReadTimeout("timeout")),
    ).publish(event("support.incident", "timeout"))
    assert result.status == "delivery_unknown" and result.attempts == 1

    calls = []
    def connects_then_succeeds(*_args, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("refused")
        return Response(204)
    result = DiscordPublisher(
        {"support": webhook("support")}, state_dir=tmp_path / "connect",
        post=connects_then_succeeds, sleep=lambda _delay: None,
    ).publish(event("support.resolved", "connect"))
    assert result.status == "delivered" and result.attempts == 2


def test_delivery_is_idempotent_across_publisher_instances(tmp_path):
    calls = []
    kwargs = dict(webhooks={"bug-reports": webhook("bugs")}, state_dir=tmp_path,
                  post=lambda *_a, **_k: calls.append(1) or Response(204), sleep=lambda _: None)
    item = event("github.issue.confirmed")
    assert DiscordPublisher(**kwargs).publish(item).status == "delivered"
    assert DiscordPublisher(**kwargs).publish(item).status == "duplicate"
    assert calls == [1]


def test_unapproved_private_and_unknown_events_are_filtered(tmp_path):
    publisher = DiscordPublisher(
        {"announcements": webhook("announcements")}, state_dir=tmp_path,
        post=lambda *_a, **_k: pytest.fail("posted"),
    )
    assert publisher.publish(DiscordEvent("1", "platform.release", "x", "x")).status == "filtered"
    assert publisher.publish(event("platform.release", "2", visibility="private")).status == "filtered"
    assert publisher.publish(event("research.private", "3")).status == "filtered"


def test_unsafe_event_id_is_rejected_before_logging_or_delivery(tmp_path):
    publisher = DiscordPublisher(
        {"support": webhook("support")}, state_dir=tmp_path,
        post=lambda *_a, **_k: pytest.fail("posted"),
    )
    with pytest.raises(ValueError):
        publisher.publish(DiscordEvent("bad\nsecret", "support.incident", "x", "x", approved=True))


def test_payload_blocks_mentions_and_honors_discord_limits(tmp_path):
    payloads = []
    publisher = DiscordPublisher(
        {"feature-requests": webhook("features")}, state_dir=tmp_path,
        post=lambda _u, **kw: payloads.append(kw["json"]) or Response(204),
    )
    item = event(
        "feature.request.accepted", title="@everyone " + "t" * 500,
        message="<@123> @here " + "m" * 9000,
        fields={f"field-{i}": "x" * 2000 for i in range(30)},
    )
    assert publisher.publish(item).status == "delivered"
    payload = payloads[0]
    embed = payload["embeds"][0]
    assert payload["allowed_mentions"] == {"parse": [], "replied_user": False}
    assert "@everyone" not in embed["title"] and "<@123>" not in embed["description"]
    assert len(embed["title"]) <= 256 and len(embed["description"]) <= 4096
    assert len(embed.get("fields", [])) <= 25
    total = len(embed["title"]) + len(embed["description"]) + len(embed["footer"]["text"])
    total += sum(len(f["name"]) + len(f["value"]) for f in embed.get("fields", []))
    assert total <= 6000


def test_webhook_secret_is_redacted_from_errors_and_dlq(tmp_path):
    secret = webhook("security")
    assert secret not in _redact(f"POST {secret} failed")

    def fail(*_args, **_kwargs):
        raise RuntimeError(f"POST {secret} failed")

    publisher = DiscordPublisher(
        {"omnibioai-alerts": secret}, state_dir=tmp_path, max_attempts=1, post=fail,
    )
    assert publisher.publish(event("security.alert")).status == "delivery_unknown"
    assert secret not in publisher.dlq_path.read_text()


def test_stale_pending_send_after_restart_becomes_ambiguous_not_resent(tmp_path):
    calls = []
    publisher = DiscordPublisher(
        {"support": webhook("support")}, state_dir=tmp_path,
        post=lambda *_a, **_k: calls.append(1) or Response(204),
    )
    item = event("support.incident", "crashed-worker")
    assert publisher._claim(item, "support") is True
    with closing(publisher._connect()) as connection, connection:
        connection.execute(
            "UPDATE discord_deliveries SET updated_at=? WHERE event_id=?",
            (time.time() - 301, item.event_id),
        )

    restarted = DiscordPublisher(
        {"support": webhook("support")}, state_dir=tmp_path,
        post=lambda *_a, **_k: calls.append(1) or Response(204),
    )
    result = restarted.publish(item)
    assert result.status == "delivery_unknown"
    assert restarted.delivery_state(item.event_id)[0] == "unknown"
    assert calls == []
