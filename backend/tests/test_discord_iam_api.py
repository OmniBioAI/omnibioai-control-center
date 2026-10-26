from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import jwt
import pytest
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient
from unittest.mock import patch

from control_center.api import routes_discord_events as routes
from control_center.core import jwt_verify
from control_center.notifications.discord_events import DiscordEventStore, parse_event_payload, sign_request

SOURCE_SECRET = "s" * 43
JWT_SECRET = "j" * 43


def issue_token(permissions=(), **claims):
    return jwt.encode({"sub": "isolated-test-operator", "permissions": list(permissions), **claims}, JWT_SECRET, algorithm="HS256")


def configured_client(monkeypatch, tmp_path):
    monkeypatch.setattr(jwt_verify, "JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("DISCORD_EVENT_GITHUB_SECRET", SOURCE_SECRET)
    app = FastAPI()
    app.include_router(routes.router)
    store = DiscordEventStore(tmp_path)
    publisher = MagicMock()
    publisher.publish.return_value = SimpleNamespace(status="delivered", attempts=1)
    publisher.delivery_state.return_value = ("delivered", 1)
    monkeypatch.setattr(routes, "_services", lambda: (store, publisher))
    monkeypatch.setattr(routes, "store_from_env", lambda: store)
    return TestClient(app), store, publisher


def event_request(client, *, nonce="nonce_for_api_test_001", signature_override=None,
                  timestamp=None, event_id="api:release:001", changes=None):
    data = {
        "event_id": event_id, "event_type": "platform.release", "source_service": "github",
        "created_at": datetime.now(timezone.utc).isoformat(), "destination_channel": "announcements",
        "approved_publication": False,
        "safe_message_payload": {"title": "test", "message": "synthetic", "color": "info", "fields": {}},
        "correlation_id": event_id,
    }
    if changes:
        data.update(changes)
    body = json.dumps(data, separators=(",", ":")).encode()
    timestamp = timestamp or str(int(time.time()))
    signature = signature_override or sign_request(SOURCE_SECRET, timestamp, nonce, body)
    return client.post("/integrations/discord/events", content=body, headers={
        "X-Omni-Discord-Source": "github", "X-Omni-Discord-Timestamp": timestamp,
        "X-Omni-Discord-Nonce": nonce, "X-Omni-Discord-Signature": signature,
        "Content-Type": "application/json",
    })


def test_api_authentication_and_global_platform_scope(monkeypatch, tmp_path):
    client, _, _ = configured_client(monkeypatch, tmp_path)
    assert client.get("/integrations/discord/events").status_code == 401
    assert client.get("/integrations/discord/events", headers={"Authorization": "Bearer invalid"}).status_code == 401
    expired = issue_token(["platform.manage_content"], exp=int(time.time()) - 10)
    assert client.get("/integrations/discord/events", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    revoked = issue_token(["platform.manage_content"], jti="revoked-integration-test")
    with patch.object(jwt_verify._blacklist, "exists", return_value=True):
        assert client.get("/integrations/discord/events", headers={"Authorization": f"Bearer {revoked}"}).status_code == 401
    tenant_user = issue_token([], tenant_id="another-tenant")
    assert client.get("/integrations/discord/events", headers={"Authorization": f"Bearer {tenant_user}"}).status_code == 403
    allowed = issue_token(["platform.manage_content"])
    assert client.get("/integrations/discord/events", headers={"Authorization": f"Bearer {allowed}"}).status_code == 200


@pytest.mark.parametrize("error", [sqlite3.OperationalError("database locked"), sqlite3.DatabaseError("storage error")])
def test_services_maps_sqlite_failures_to_redacted_503(monkeypatch, error):
    def fail_store():
        raise error

    monkeypatch.setattr(routes, "store_from_env", fail_store)
    with pytest.raises(HTTPException) as raised:
        routes._services()
    assert raised.value.status_code == 503
    assert raised.value.detail == "Discord event storage is unavailable"
    assert "database locked" not in raised.value.detail
    assert "storage error" not in raised.value.detail


def test_every_sqlite_route_failure_is_a_redacted_503(monkeypatch, tmp_path):
    client, store, _ = configured_client(monkeypatch, tmp_path)
    editor = {"Authorization": f"Bearer {issue_token(['platform.manage_content'])}"}
    infra = {"Authorization": f"Bearer {issue_token(['platform.manage_infra'])}"}
    failure = sqlite3.OperationalError("private database path and lock detail")

    with patch.object(store, "consume_nonce", side_effect=failure):
        responses = [event_request(client, nonce="nonce_storage_error_01")]
    with patch.object(store, "sync_confirmed_deliveries", side_effect=failure):
        responses.extend([
            client.get("/integrations/discord/events", headers=editor),
            client.get("/integrations/discord/events/event-id", headers=infra),
        ])
    with patch.object(store, "approve", side_effect=failure):
        responses.append(client.post("/integrations/discord/events/event-id/approve", headers=editor))
    with patch.object(store, "get", side_effect=failure):
        responses.extend([
            client.post("/integrations/discord/events/event-id/replay", headers=infra),
            client.post("/integrations/discord/events/event-id/recover", headers=infra),
        ])
    with patch.object(store, "reconcile_unknown", side_effect=failure):
        responses.append(client.post(
            "/integrations/discord/events/event-id/reconcile",
            json={"outcome": "delivered"}, headers=infra,
        ))

    assert all(response.status_code == 503 for response in responses)
    assert all(response.json()["detail"] == "Discord event storage is unavailable" for response in responses)
    assert all("private database" not in response.text for response in responses)


def test_delivery_ledger_failures_after_route_initialization_are_redacted(monkeypatch, tmp_path):
    client, store, _ = configured_client(monkeypatch, tmp_path)
    editor = {"Authorization": f"Bearer {issue_token(['platform.manage_content'])}"}
    infra = {"Authorization": f"Bearer {issue_token(['platform.manage_infra'])}"}
    failure = sqlite3.DatabaseError("private delivery ledger detail")

    monkeypatch.setenv(
        "DISCORD_EVENT_APPROVAL_SOURCES", json.dumps({"github": ["platform.release"]}),
    )
    with patch.object(routes, "_deliver", side_effect=failure):
        ingested = event_request(
            client, nonce="nonce_delivery_error_00", event_id="api:delivery-error:ingest",
            changes={"approved_publication": True},
        )

    pending = event_request(client, nonce="nonce_delivery_error_01", event_id="api:delivery-error:approve").json()
    with patch.object(routes, "_deliver", side_effect=failure):
        approved = client.post(
            f"/integrations/discord/events/{pending['event_id']}/approve", headers=editor,
        )

    replay_id = "api:delivery-error:replay"
    event_request(client, nonce="nonce_delivery_error_02", event_id=replay_id)
    store.approve(replay_id, "operator")
    store.update_delivery(replay_id, status="failed", attempts=1)
    with patch.object(routes, "_deliver", side_effect=failure):
        replayed = client.post(f"/integrations/discord/events/{replay_id}/replay", headers=infra)

    recover_id = "api:delivery-error:recover"
    event_request(client, nonce="nonce_delivery_error_03", event_id=recover_id)
    store.approve(recover_id, "operator")
    with patch.object(routes, "_deliver", side_effect=failure):
        recovered = client.post(f"/integrations/discord/events/{recover_id}/recover", headers=infra)

    for response in (ingested, approved, replayed, recovered):
        assert response.status_code == 503
        assert response.json()["detail"] == "Discord event storage is unavailable"
        assert "private delivery" not in response.text


def test_api_requires_editorial_permission_and_keeps_source_events_pending(monkeypatch, tmp_path):
    client, store, publisher = configured_client(monkeypatch, tmp_path)
    assert event_request(client, signature_override="v1=forged").status_code == 401
    response = event_request(client)
    assert response.status_code == 202
    event_id = response.json()["event_id"]
    no_approval = issue_token(["platform.manage_infra"])
    denied = client.post(f"/integrations/discord/events/{event_id}/approve", headers={"Authorization": f"Bearer {no_approval}"})
    assert denied.status_code == 403
    assert store.get(event_id)["approval_state"] == "pending"
    editor = issue_token(["platform.manage_content"])
    accepted = client.post(f"/integrations/discord/events/{event_id}/approve", headers={"Authorization": f"Bearer {editor}"})
    assert accepted.status_code == 200
    assert accepted.json()["approval_state"] == "approved"
    publisher.publish.assert_called_once()


def test_server_authorized_source_approval_dispatches_only_allowed_event(monkeypatch, tmp_path):
    client, _, publisher = configured_client(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "DISCORD_EVENT_APPROVAL_SOURCES", json.dumps({"github": ["platform.release"]}),
    )
    response = event_request(
        client, nonce="nonce_api_approved_001", event_id="api:approved:001",
        changes={"approved_publication": True},
    )
    assert response.status_code == 200
    assert response.json()["approval_state"] == "approved"
    publisher.publish.assert_called_once()


def test_queue_inspection_and_replay_require_infrastructure_permission(monkeypatch, tmp_path):
    client, store, _ = configured_client(monkeypatch, tmp_path)
    response = event_request(client)
    event_id = response.json()["event_id"]
    store.approve(event_id, "test")
    store.update_delivery(event_id, status="failed", attempts=1, error="sanitized")
    editor = issue_token(["platform.manage_content"])
    assert client.get(f"/integrations/discord/events/{event_id}", headers={"Authorization": f"Bearer {editor}"}).status_code == 403
    assert client.post(f"/integrations/discord/events/{event_id}/replay", headers={"Authorization": f"Bearer {editor}"}).status_code == 403
    infra = issue_token(["platform.manage_infra"])
    assert client.get(f"/integrations/discord/events/{event_id}", headers={"Authorization": f"Bearer {infra}"}).status_code == 200
    assert client.post(f"/integrations/discord/events/{event_id}/replay", headers={"Authorization": f"Bearer {infra}"}).status_code == 200


def test_signed_ingestion_replay_deduplication_and_validation_errors(monkeypatch, tmp_path):
    client, _, publisher = configured_client(monkeypatch, tmp_path)
    fixed = {"created_at": "2026-01-01T00:00:00+00:00"}
    first = event_request(client, nonce="nonce_api_replay_0001", event_id="api:stable:001", changes=fixed)
    assert first.status_code == 202
    duplicate = event_request(client, nonce="nonce_api_replay_0002", event_id="api:stable:001", changes=fixed)
    assert duplicate.status_code == 202 and duplicate.json()["duplicate"] is True
    conflict = event_request(client, nonce="nonce_api_replay_0003", event_id="api:stable:001", changes={
        **fixed, "safe_message_payload": {"title": "changed", "message": "different", "fields": {}},
    })
    assert conflict.status_code == 409
    assert publisher.publish.call_count == 0
    assert event_request(client, nonce="nonce_api_expired_01", timestamp=str(int(time.time()) - 301)).status_code == 401
    assert event_request(client, nonce="nonce_api_route_0001", changes={"destination_channel": "support"}).status_code == 422
    assert event_request(client, nonce="nonce_api_forged_001", changes={"approved_publication": True}).status_code == 403
    oversized = client.post("/integrations/discord/events", content=b"x" * (routes.MAX_EVENT_BODY_BYTES + 1))
    assert oversized.status_code == 413


def test_operator_event_lifecycle_query_recover_and_reconcile(monkeypatch, tmp_path):
    client, store, _ = configured_client(monkeypatch, tmp_path)
    editor = issue_token(["platform.manage_content"])
    infra = issue_token(["platform.manage_infra"])
    edit_headers = {"Authorization": f"Bearer {editor}"}
    infra_headers = {"Authorization": f"Bearer {infra}"}
    assert client.get("/integrations/discord/events?status=not-a-state", headers=edit_headers).status_code == 422
    assert client.get("/integrations/discord/events/missing", headers=infra_headers).status_code == 404
    assert client.post("/integrations/discord/events/missing/approve", headers=edit_headers).status_code == 404
    assert client.post("/integrations/discord/events/missing/replay", headers=infra_headers).status_code == 404
    assert client.post("/integrations/discord/events/missing/recover", headers=infra_headers).status_code == 404
    assert client.post("/integrations/discord/events/missing/reconcile", json={"outcome": "delivered"}, headers=infra_headers).status_code == 404

    queued_id = "api:recover:001"
    event_request(client, nonce="nonce_api_recover_0001", event_id=queued_id)
    store.approve(queued_id, "editor")
    recovered = client.post(f"/integrations/discord/events/{queued_id}/recover", headers=infra_headers)
    assert recovered.status_code == 200 and recovered.json()["delivery_status"] == "delivered"
    assert client.post(f"/integrations/discord/events/{queued_id}/recover", headers=infra_headers).status_code == 409

    unknown_id = "api:reconcile:001"
    event_request(client, nonce="nonce_api_reconcile_01", event_id=unknown_id)
    store.update_delivery(unknown_id, status="delivery_unknown", attempts=1, error="ambiguous")
    assert client.post(f"/integrations/discord/events/{unknown_id}/reconcile", json={"outcome": "unsure"}, headers=infra_headers).status_code == 422
    assert client.post(f"/integrations/discord/events/{unknown_id}/reconcile", json={"outcome": "delivered"}, headers=infra_headers).status_code == 200
    assert client.post(f"/integrations/discord/events/{unknown_id}/reconcile", json={"outcome": "delivered"}, headers=infra_headers).status_code == 409


def test_operator_conflict_paths_are_explicit_and_non_mutating(monkeypatch, tmp_path):
    client, store, _ = configured_client(monkeypatch, tmp_path)
    editor = {"Authorization": f"Bearer {issue_token(['platform.manage_content'])}"}
    infra = {"Authorization": f"Bearer {issue_token(['platform.manage_infra'])}"}

    rejected_id = "api:rejected:001"
    event_request(client, nonce="nonce_api_rejected_01", event_id=rejected_id)
    with closing(store._connect()) as connection, connection:
        connection.execute(
            "UPDATE discord_event_records SET approval_state='rejected' WHERE event_id=?", (rejected_id,),
        )
    assert client.post(f"/integrations/discord/events/{rejected_id}/approve", headers=editor).status_code == 409

    pending_id = "api:pending-replay:001"
    event_request(client, nonce="nonce_api_pending_replay", event_id=pending_id)
    assert client.post(f"/integrations/discord/events/{pending_id}/replay", headers=infra).status_code == 409

    ambiguous_id = "api:invalid-reconcile:001"
    event_request(client, nonce="nonce_api_invalid_reconcile", event_id=ambiguous_id)
    store.update_delivery(ambiguous_id, status="delivery_unknown", attempts=1, error="ambiguous")
    monkeypatch.setattr(
        store, "reconcile_unknown", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("internal detail")),
    )
    response = client.post(
        f"/integrations/discord/events/{ambiguous_id}/reconcile", json={"outcome": "delivered"}, headers=infra,
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "invalid reconciliation outcome"


def test_service_configuration_errors_fail_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(routes, "store_from_env", lambda: (_ for _ in ()).throw(OSError("private-path")))
    with pytest.raises(HTTPException) as raised:
        routes._services()
    assert raised.value.status_code == 503
    assert "private-path" not in raised.value.detail


def test_services_initialize_and_recover_store_before_returning(monkeypatch, tmp_path):
    store = DiscordEventStore(tmp_path)
    publisher = MagicMock()
    with patch.object(routes, "store_from_env", return_value=store), \
            patch.object(routes.DiscordPublisher, "from_env", return_value=publisher):
        actual_store, actual_publisher = routes._services()
    assert actual_store is store
    assert actual_publisher is publisher


@pytest.mark.parametrize("state,expected", [
    (("delivered", 1), "delivered"),
    (("failed", 2), "failed"),
    (("unknown", 1), "delivery_unknown"),
    (("pending", 0), "delivering"),
    (None, "delivering"),
])
def test_duplicate_delivery_receipt_reconciles_only_known_states(tmp_path, state, expected):
    store = DiscordEventStore(tmp_path)
    body = json.dumps({
        "event_id": "api:duplicate:001", "event_type": "platform.release",
        "source_service": "github", "created_at": datetime.now(timezone.utc).isoformat(),
        "destination_channel": "announcements", "approved_publication": False,
        "safe_message_payload": {"title": "safe", "message": "synthetic", "color": "info", "fields": {}},
        "correlation_id": "api:duplicate:001",
    }).encode()
    event, payload = parse_event_payload(body, authenticated_source="github")
    record, _ = store.ingest(event, payload)
    record = store.approve(event.event_id, "operator")
    publisher = SimpleNamespace(
        publish=lambda *_a, **_k: SimpleNamespace(status="duplicate", attempts=1),
        delivery_state=lambda _event_id: state,
    )
    reconciled = routes._deliver(store, publisher, record)
    assert reconciled["delivery_status"] == expected


def test_failed_publisher_result_is_recorded_without_internal_error_details(tmp_path):
    store = DiscordEventStore(tmp_path)
    body = json.dumps({
        "event_id": "api:failed:001", "event_type": "platform.release",
        "source_service": "github", "created_at": datetime.now(timezone.utc).isoformat(),
        "destination_channel": "announcements", "approved_publication": False,
        "safe_message_payload": {"title": "safe", "message": "synthetic", "color": "info", "fields": {}},
        "correlation_id": "api:failed:001",
    }).encode()
    event, payload = parse_event_payload(body, authenticated_source="github")
    record, _ = store.ingest(event, payload)
    record = store.approve(event.event_id, "operator")
    publisher = SimpleNamespace(publish=lambda *_a, **_k: SimpleNamespace(status="failed", attempts=4))
    failed = routes._deliver(store, publisher, record)
    assert failed["delivery_status"] == "failed"
    assert failed["last_error"] == "delivery exhausted or rejected"

