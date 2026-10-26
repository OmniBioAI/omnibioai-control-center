"""Authentication, schema, persistence, approval, and replay tests."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import gc
import warnings
from datetime import datetime, timezone

import pytest

from control_center.notifications.discord import DiscordEvent, DiscordPublisher
from control_center.notifications.discord_events import (
    DiscordApprovalError,
    DiscordEventConflictError,
    DiscordEventStore,
    DiscordEventValidationError,
    DiscordSourceAuthError,
    load_approval_sources,
    load_source_secrets,
    parse_event_payload,
    sign_request,
    store_from_env,
    verify_request_signature,
)

SECRET = "s" * 43
WEBHOOK = "https://discord.com/api/webhooks/123456/test-token"


def test_discord_ledgers_explicitly_close_connections(monkeypatch, tmp_path):
    opened = []
    original_connect = sqlite3.connect

    class TrackedConnection(sqlite3.Connection):
        closed = False

        def close(self):
            self.closed = True
            return super().close()

    def tracked_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs, factory=TrackedConnection)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)
    with warnings.catch_warnings():
        warnings.simplefilter("error", ResourceWarning)
        store = DiscordEventStore(tmp_path)
        event, raw = parse_event_payload(encoded(), authenticated_source="github")
        store.consume_nonce("github", "connection_close_nonce")
        store.ingest(event, raw)
        store.list_events()
        publisher = DiscordPublisher({"announcements": WEBHOOK}, state_dir=tmp_path)
        publisher.delivery_state(event.event_id)
        gc.collect()
    assert opened
    assert all(connection.closed for connection in opened)


def test_store_from_env_uses_configured_persistent_state_dir(tmp_path):
    store = store_from_env({"DISCORD_DELIVERY_STATE_DIR": str(tmp_path / "events")})
    assert store.path == tmp_path / "events" / "deliveries.sqlite3"


def envelope(**changes):
    data = {
        "event_id": "release:123",
        "event_type": "platform.release",
        "source_service": "github",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "destination_channel": "announcements",
        "approved_publication": False,
        "safe_message_payload": {
            "title": "Release test",
            "message": "Version 1.2.3 is available.",
            "color": "success",
            "fields": {"Version": "1.2.3"},
        },
        "correlation_id": "github:run:123",
    }
    data.update(changes)
    return data


def encoded(**changes):
    return json.dumps(envelope(**changes), separators=(",", ":")).encode()


def test_source_secret_and_approval_policy_validation():
    assert load_source_secrets({"DISCORD_EVENT_SOURCE_SECRETS": json.dumps({"github": SECRET})}) == {"github": (SECRET,)}
    assert load_source_secrets({"DISCORD_EVENT_GITHUB_SECRET": SECRET}) == {"github": (SECRET,)}
    with pytest.raises(DiscordSourceAuthError):
        load_source_secrets({"DISCORD_EVENT_SOURCE_SECRETS": json.dumps({"github": "short"})})
    with pytest.raises(DiscordSourceAuthError):
        load_source_secrets({"DISCORD_EVENT_GITHUB_SECRET": "s" * 32})
    assert load_source_secrets({
        "DISCORD_EVENT_GITHUB_SECRET": SECRET,
        "DISCORD_EVENT_GITHUB_PREVIOUS_SECRET": "p" * 43,
    })["github"] == (SECRET, "p" * 43)
    policy = load_approval_sources({
        "DISCORD_EVENT_APPROVAL_SOURCES": json.dumps({"github": ["platform.release"]})
    })
    assert policy["github"] == frozenset({"platform.release"})
    with pytest.raises(DiscordSourceAuthError):
        load_approval_sources({
            "DISCORD_EVENT_APPROVAL_SOURCES": json.dumps({"github": ["security.alert"]})
        })


def test_source_secret_loader_rejects_duplicate_per_source_environment_keys():
    duplicate = "d" * 43
    with pytest.raises(DiscordSourceAuthError, match="unique across source identities") as exc:
        load_source_secrets({
            "DISCORD_EVENT_GITHUB_SECRET": duplicate,
            "DISCORD_EVENT_RAG_SECRET": duplicate,
        })
    assert duplicate not in str(exc.value)


def test_source_secret_loader_rejects_duplicate_json_map_keys():
    duplicate = "e" * 43
    with pytest.raises(DiscordSourceAuthError, match="unique across source identities") as exc:
        load_source_secrets({
            "DISCORD_EVENT_SOURCE_SECRETS": json.dumps({
                "github": duplicate, "rag": duplicate,
            }),
        })
    assert duplicate not in str(exc.value)


@pytest.mark.parametrize("env", [
    {"DISCORD_EVENT_SOURCE_SECRETS": "{"},
    {"DISCORD_EVENT_SOURCE_SECRETS": "[]"},
    {"DISCORD_EVENT_SOURCE_SECRETS": json.dumps({"unknown": SECRET})},
    {"DISCORD_EVENT_SOURCE_SECRETS": json.dumps({"github": [SECRET, SECRET, SECRET]})},
    {"DISCORD_EVENT_GITHUB_PREVIOUS_SECRET": "p" * 43},
    {"DISCORD_EVENT_GITHUB_SECRET": SECRET, "DISCORD_EVENT_GITHUB_PREVIOUS_SECRET": "short"},
])
def test_source_secret_configuration_fails_closed(env):
    with pytest.raises(DiscordSourceAuthError):
        load_source_secrets(env)


@pytest.mark.parametrize("env", [
    {"DISCORD_EVENT_APPROVAL_SOURCES": "{"},
    {"DISCORD_EVENT_APPROVAL_SOURCES": "[]"},
    {"DISCORD_EVENT_APPROVAL_SOURCES": json.dumps({"unknown": []})},
    {"DISCORD_EVENT_APPROVAL_SOURCES": json.dumps({"github": "platform.release"})},
])
def test_approval_policy_configuration_fails_closed(env):
    with pytest.raises(DiscordSourceAuthError):
        load_approval_sources(env)


def test_signature_verification_and_negative_paths():
    body = encoded()
    timestamp = str(int(time.time()))
    nonce = "abcdefghijklmnop"
    signature = sign_request(SECRET, timestamp, nonce, body)
    verify_request_signature(
        source="github", timestamp=timestamp, nonce=nonce, signature=signature,
        body=body, secrets={"github": SECRET}, now=int(timestamp),
    )
    old_signature = sign_request("p" * 43, timestamp, "qrstuvwxyzABCDEF", body)
    verify_request_signature(
        source="github", timestamp=timestamp, nonce="qrstuvwxyzABCDEF",
        signature=old_signature, body=body,
        secrets={"github": (SECRET, "p" * 43)}, now=int(timestamp),
    )
    with pytest.raises(DiscordSourceAuthError):
        verify_request_signature(
            source="support", timestamp=timestamp, nonce="abcdefghijklmnop",
            signature=signature, body=body, secrets={"github": SECRET}, now=int(timestamp),
        )
    for values in (
        {"signature": "v1=bad"},
        {"timestamp": str(int(timestamp) - 301)},
        {"source": "unknown"},
        {"nonce": "short"},
    ):
        args = dict(source="github", timestamp=timestamp, nonce=nonce, signature=signature,
                    body=body, secrets={"github": SECRET}, now=int(timestamp))
        args.update(values)
        with pytest.raises(DiscordSourceAuthError):
            verify_request_signature(**args)
    for timestamp in ("not-a-timestamp", ""):
        with pytest.raises(DiscordSourceAuthError):
            verify_request_signature(
                source="github", timestamp=timestamp, nonce=nonce, signature=signature,
                body=body, secrets={"github": SECRET}, now=int(time.time()),
            )
    with pytest.raises(DiscordSourceAuthError):
        verify_request_signature(
            source="bad source", timestamp=timestamp, nonce=nonce,
            signature=signature, body=body, secrets={"bad source": SECRET},
        )


def test_payload_schema_and_source_authorization():
    event, raw = parse_event_payload(encoded(), authenticated_source="github")
    assert event.destination_channel == "announcements"
    assert not event.approved
    assert raw["correlation_id"] == event.correlation_id
    with pytest.raises(DiscordEventValidationError):
        parse_event_payload(encoded(destination_channel="support"), authenticated_source="github")
    with pytest.raises(DiscordEventValidationError):
        parse_event_payload(encoded(event_type="security.alert"), authenticated_source="github")
    with pytest.raises(DiscordEventValidationError):
        parse_event_payload(encoded(source_service="rag"), authenticated_source="github")


@pytest.mark.parametrize("raw,source", [
    (b"not-json", "github"),
    (b"[]", "github"),
    (json.dumps({**envelope(), "extra": True}).encode(), "github"),
    (encoded(event_id="bad id"), "github"),
    (encoded(correlation_id="bad id"), "github"),
    (encoded(created_at="not-an-iso-date"), "github"),
    (encoded(created_at="2026-01-01T00:00:00"), "github"),
    (encoded(created_at="2999-01-01T00:00:00+00:00"), "github"),
    (encoded(approved_publication="yes"), "github"),
    (encoded(safe_message_payload=[]), "github"),
    (encoded(safe_message_payload={"title": "", "message": "safe"}), "github"),
    (encoded(safe_message_payload={"title": "safe", "message": ""}), "github"),
    (encoded(safe_message_payload={"title": "safe", "message": "x" * 12001}), "github"),
    (encoded(safe_message_payload={"title": "safe", "message": "safe", "color": "purple"}), "github"),
    (encoded(safe_message_payload={"title": "safe", "message": "safe", "fields": {"k": [1]}}), "github"),
    (encoded(safe_message_payload={"title": "safe", "message": "safe", "fields": {"Email": "person@example.org"}}), "github"),
])
def test_event_payload_schema_rejects_invalid_values(raw, source):
    with pytest.raises(DiscordEventValidationError):
        parse_event_payload(raw, authenticated_source=source)


def test_source_cannot_self_approve_without_deployment_policy():
    with pytest.raises(DiscordApprovalError):
        parse_event_payload(encoded(approved_publication=True), authenticated_source="github")
    event, _ = parse_event_payload(
        encoded(approved_publication=True), authenticated_source="github",
        approval_sources={"github": frozenset({"platform.release"})},
    )
    assert event.approved


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "Contact person@example.org", "message": "safe"},
        {"title": "Safe", "message": "safe", "fields": {"Patient ID": "42"}},
        {"title": "Safe", "message": "safe", "fields": {"Dataset": "private"}},
        {"title": "Safe", "message": "safe", "unexpected": "field"},
    ],
)
def test_sensitive_or_unknown_payload_content_is_rejected(payload):
    with pytest.raises(DiscordEventValidationError):
        parse_event_payload(encoded(safe_message_payload=payload), authenticated_source="github")


def test_store_migrations_are_versioned_and_compatible_with_v1_database(tmp_path):
    path = tmp_path / "deliveries.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE discord_deliveries (
                event_id TEXT PRIMARY KEY,event_type TEXT NOT NULL,channel TEXT NOT NULL,
                status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,updated_at REAL NOT NULL
            )"""
        )
    store = DiscordEventStore(tmp_path)
    with sqlite3.connect(path) as connection:
        assert [row[0] for row in connection.execute(
            "SELECT version FROM discord_schema_migrations ORDER BY version"
        )] == [1, 2, 3]
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name='discord_deliveries'"
        ).fetchone()
    assert store.path == path


def test_durable_ingest_dedup_conflict_approval_and_receipt(tmp_path):
    store = DiscordEventStore(tmp_path)
    assert store.state_dir.stat().st_mode & 0o777 == 0o700
    assert store.path.stat().st_mode & 0o777 == 0o600
    event, raw = parse_event_payload(encoded(), authenticated_source="github")
    record, duplicate = store.ingest(event, raw)
    assert not duplicate and record["delivery_status"] == "pending_approval"
    assert store.list_events() == [store.public_record(record)]
    with pytest.raises(ValueError):
        store.list_events(status="all")
    with pytest.raises(ValueError):
        store.list_events(limit=0)
    with pytest.raises(KeyError):
        store.get("missing:event")
    assert DiscordEventStore(tmp_path).get(event.event_id)["correlation_id"] == event.correlation_id
    _, duplicate = store.ingest(event, raw)
    assert duplicate
    changed = dict(raw)
    changed["correlation_id"] = "github:run:changed"
    changed_event = DiscordEvent(**{**event.__dict__, "correlation_id": "github:run:changed"})
    with pytest.raises(DiscordEventConflictError):
        store.ingest(changed_event, changed)
    approved = store.approve(event.event_id, "operator-123")
    assert approved["approval_state"] == "approved"
    delivered = store.update_delivery(event.event_id, status="delivered", attempts=1)
    assert json.loads(delivered["receipt_json"])["status"] == "delivered"
    public = store.public_record(delivered)
    assert "payload_json" not in public and public["approved_by"] == "operator-123"


def test_nonce_replay_is_rejected_and_expired_nonces_are_reaped(tmp_path):
    store = DiscordEventStore(tmp_path)
    store.consume_nonce("github", "abcdefghijklmnop", now=1000)
    with pytest.raises(DiscordSourceAuthError):
        store.consume_nonce("github", "abcdefghijklmnop", now=1001)
    store.consume_nonce("github", "abcdefghijklmnop", now=1701)


def test_store_reconciliation_and_approval_state_conflicts(tmp_path):
    store = DiscordEventStore(tmp_path)
    event, raw = parse_event_payload(encoded(), authenticated_source="github")
    store.ingest(event, raw)
    with pytest.raises(KeyError):
        store.reconcile_unknown("missing:event", outcome="delivered", reconciled_by="operator")
    with pytest.raises(DiscordEventConflictError):
        store.reconcile_unknown(event.event_id, outcome="delivered", reconciled_by="operator")
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE discord_event_records SET approval_state='rejected' WHERE event_id=?", (event.event_id,))
    with pytest.raises(DiscordEventConflictError):
        store.approve(event.event_id, "operator")


def test_event_store_without_legacy_delivery_table_syncs_safely(tmp_path):
    store = DiscordEventStore(tmp_path)
    assert store.sync_confirmed_deliveries() == 0


def test_crash_before_dispatch_leaves_recoverable_approved_queue(tmp_path):
    store = DiscordEventStore(tmp_path)
    event, raw = parse_event_payload(
        encoded(approved_publication=True), authenticated_source="github",
        approval_sources={"github": frozenset({"platform.release"})},
    )
    record, duplicate = store.ingest(event, raw)
    assert not duplicate
    assert record["delivery_status"] == "queued"
    assert store.list_events(status="queued")[0]["event_id"] == event.event_id
    # A newly constructed store sees the durable queue after process restart.
    assert DiscordEventStore(tmp_path).get(event.event_id)["delivery_status"] == "queued"


def test_crash_during_http_is_ambiguous_and_requires_operator_reconciliation(tmp_path):
    store = DiscordEventStore(tmp_path)
    event, raw = parse_event_payload(encoded(), authenticated_source="github")
    store.ingest(event, raw)
    store.update_delivery(event.event_id, status="delivering", attempts=1)

    restarted = DiscordEventStore(tmp_path)
    assert restarted.recover_inflight(now=time.time() + 61, lease_seconds=60) == 1
    assert restarted.get(event.event_id)["delivery_status"] == "delivery_unknown"
    assert restarted.list_events(status="delivery_unknown")[0]["event_id"] == event.event_id
    with pytest.raises(ValueError):
        restarted.reconcile_unknown(event.event_id, outcome="unsure", reconciled_by="operator")

    # Operator confirms no visible Discord post: only then is replay eligible.
    failed = restarted.reconcile_unknown(
        event.event_id, outcome="not_delivered", reconciled_by="operator-123",
    )
    assert failed["delivery_status"] == "failed"
    assert failed["reconciliation"] == "not_delivered"
    assert failed["reconciled_by"] == "operator-123"


def test_local_2xx_receipt_recovers_crash_before_event_receipt_write(tmp_path):
    store = DiscordEventStore(tmp_path)
    publisher = DiscordPublisher({"announcements": WEBHOOK}, state_dir=tmp_path, post=lambda *_a, **_k: type("R", (), {"status_code": 204})())
    event, raw = parse_event_payload(
        encoded(approved_publication=True), authenticated_source="github",
        approval_sources={"github": frozenset({"platform.release"})},
    )
    store.ingest(event, raw)
    store.update_delivery(event.event_id, status="delivering", attempts=0)
    assert publisher.publish(event).status == "delivered"
    # Simulate a crash between publisher 2xx persistence and event-store update.
    assert store.get(event.event_id)["delivery_status"] == "delivering"
    assert DiscordEventStore(tmp_path).sync_confirmed_deliveries() == 1
    recovered = DiscordEventStore(tmp_path).get(event.event_id)
    assert recovered["delivery_status"] == "delivered"
    assert json.loads(recovered["receipt_json"])["recovered_from_local_receipt"] is True


def test_concurrent_publisher_claim_allows_exactly_one_delivery(tmp_path):
    calls = []
    barrier = threading.Barrier(2)

    class Response:
        status_code = 204

    def post(*_args, **_kwargs):
        calls.append(1)
        return Response()

    item = DiscordEvent(
        "support:concurrent", "support.incident", "Test", "Public test",
        approved=True, source_service="support", destination_channel="support",
        correlation_id="support:concurrent",
    )
    results = []

    def run():
        publisher = DiscordPublisher({"support": WEBHOOK}, state_dir=tmp_path, post=post)
        barrier.wait()
        results.append(publisher.publish(item).status)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["delivered", "duplicate"]
    assert calls == [1]


def test_failed_delivery_can_only_be_replayed_explicitly(tmp_path):
    class Response:
        def __init__(self, status_code):
            self.status_code = status_code
            self.headers = {}

        def json(self):
            return {}

    responses = iter([Response(400), Response(204)])
    publisher = DiscordPublisher(
        {"support": WEBHOOK}, state_dir=tmp_path, max_attempts=1,
        post=lambda *_a, **_kw: next(responses),
    )
    item = DiscordEvent("support:replay", "support.incident", "Test", "Test", approved=True)
    assert publisher.publish(item).status == "failed"
    assert publisher.publish(item).status == "duplicate"
    assert publisher.publish(item, replay=True).status == "delivered"
