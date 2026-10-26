"""Authenticated ingestion, approval, receipts, and DLQ replay for Discord events."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from control_center.core.auth import require_permission
from control_center.notifications.discord import DiscordConfigError, DiscordPublisher
from control_center.notifications.discord_events import (
    DiscordApprovalError,
    DiscordEventConflictError,
    DiscordEventStore,
    DiscordEventValidationError,
    DiscordSourceAuthError,
    load_approval_sources,
    load_source_secrets,
    parse_event_payload,
    store_from_env,
    verify_request_signature,
)

router = APIRouter(prefix="/integrations/discord", tags=["discord-events"])
MAX_EVENT_BODY_BYTES = 16 * 1024


def _services() -> tuple[DiscordEventStore, DiscordPublisher]:
    try:
        store = store_from_env()
        publisher = DiscordPublisher.from_env()
        store.sync_confirmed_deliveries()
        store.recover_inflight()
        return store, publisher
    except sqlite3.Error:
        raise HTTPException(503, "Discord event storage is unavailable") from None
    except (DiscordConfigError, OSError):
        raise HTTPException(503, "Discord event delivery is not safely configured") from None


def _deliver(store: DiscordEventStore, publisher: DiscordPublisher, record: dict[str, Any], *, replay: bool = False) -> dict[str, Any]:
    event = store.event_from_record(record)
    store.update_delivery(event.event_id, status="delivering", attempts=record.get("attempts", 0))
    result = publisher.publish(event, replay=replay)
    if result.status == "duplicate":
        state = publisher.delivery_state(event.event_id)
        if state and state[0] == "delivered":
            return store.update_delivery(event.event_id, status="delivered", attempts=state[1])
        if state and state[0] == "failed":
            return store.update_delivery(
                event.event_id, status="failed", attempts=state[1], error="previous delivery failed",
            )
        if state and state[0] == "unknown":
            return store.update_delivery(
                event.event_id, status="delivery_unknown", attempts=state[1],
                error="delivery outcome requires operator reconciliation",
            )
        # Another worker owns a live pending claim, or the outcome is still
        # uncertain. Keep the central record in delivering; stale leases are
        # converted to delivery_unknown and require explicit reconciliation.
        return store.get(event.event_id)
    error = "delivery exhausted or rejected" if result.status == "failed" else None
    return store.update_delivery(
        event.event_id, status=result.status, attempts=result.attempts, error=error,
    )


@router.post("/events")
async def ingest_discord_event(
    request: Request,
    x_omni_discord_source: str = Header(default=""),
    x_omni_discord_timestamp: str = Header(default=""),
    x_omni_discord_nonce: str = Header(default=""),
    x_omni_discord_signature: str = Header(default=""),
) -> JSONResponse:
    body = await request.body()
    if len(body) > MAX_EVENT_BODY_BYTES:
        raise HTTPException(413, "Discord event payload is too large")
    store, publisher = _services()
    try:
        verify_request_signature(
            source=x_omni_discord_source, timestamp=x_omni_discord_timestamp,
            nonce=x_omni_discord_nonce, signature=x_omni_discord_signature,
            body=body, secrets=load_source_secrets(),
        )
        store.consume_nonce(x_omni_discord_source, x_omni_discord_nonce)
        event, envelope = parse_event_payload(
            body, authenticated_source=x_omni_discord_source,
            approval_sources=load_approval_sources(),
        )
        record, duplicate = store.ingest(event, envelope)
    except DiscordApprovalError as exc:
        raise HTTPException(403, str(exc)) from exc
    except DiscordSourceAuthError as exc:
        raise HTTPException(401, "Discord event source authentication failed") from exc
    except DiscordEventValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    except DiscordEventConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except sqlite3.Error:
        raise HTTPException(503, "Discord event storage is unavailable") from None

    if not duplicate and event.approved:
        try:
            record = _deliver(store, publisher, record)
        except sqlite3.Error:
            raise HTTPException(503, "Discord event storage is unavailable") from None
    response = DiscordEventStore.public_record(record)
    response["duplicate"] = duplicate
    return JSONResponse(response, status_code=200 if record["delivery_status"] == "delivered" else 202)


@router.get("/events")
def list_discord_events(
    status: str = "pending_approval",
    limit: int = 100,
    _operator: dict = Depends(require_permission("platform.manage_content")),
) -> JSONResponse:
    try:
        store = store_from_env()
        store.sync_confirmed_deliveries()
        store.recover_inflight()
        events = store.list_events(status=status, limit=limit)
    except ValueError as exc:
        raise HTTPException(422, "invalid event query") from exc
    except sqlite3.Error:
        raise HTTPException(503, "Discord event storage is unavailable") from None
    return JSONResponse({"events": events})


@router.get("/events/{event_id}")
def get_discord_event(
    event_id: str,
    _operator: dict = Depends(require_permission("platform.manage_infra")),
) -> JSONResponse:
    try:
        store = store_from_env()
        store.sync_confirmed_deliveries()
        store.recover_inflight()
        record = store.get(event_id)
    except KeyError as exc:
        raise HTTPException(404, "Discord event not found") from exc
    except sqlite3.Error:
        raise HTTPException(503, "Discord event storage is unavailable") from None
    return JSONResponse(DiscordEventStore.public_record(record))


@router.post("/events/{event_id}/approve")
def approve_discord_event(
    event_id: str,
    operator: dict = Depends(require_permission("platform.manage_content")),
) -> JSONResponse:
    store, publisher = _services()
    try:
        record = store.approve(event_id, str(operator.get("sub") or "unknown-operator"))
        record = _deliver(store, publisher, record)
    except KeyError as exc:
        raise HTTPException(404, "Discord event not found") from exc
    except DiscordEventConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except sqlite3.Error:
        raise HTTPException(503, "Discord event storage is unavailable") from None
    return JSONResponse(DiscordEventStore.public_record(record))


@router.post("/events/{event_id}/replay")
def replay_discord_event(
    event_id: str,
    _operator: dict = Depends(require_permission("platform.manage_infra")),
) -> JSONResponse:
    store, publisher = _services()
    try:
        record = store.get(event_id)
    except KeyError as exc:
        raise HTTPException(404, "Discord event not found") from exc
    except sqlite3.Error:
        raise HTTPException(503, "Discord event storage is unavailable") from None
    if record["approval_state"] != "approved" or record["delivery_status"] != "failed":
        raise HTTPException(409, "only approved failed events can be replayed")
    try:
        record = _deliver(store, publisher, record, replay=True)
    except sqlite3.Error:
        raise HTTPException(503, "Discord event storage is unavailable") from None
    return JSONResponse(DiscordEventStore.public_record(record))


@router.post("/events/{event_id}/recover")
def recover_queued_discord_event(
    event_id: str,
    _operator: dict = Depends(require_permission("platform.manage_infra")),
) -> JSONResponse:
    """Dispatch an approved event persisted before the prior process started sending."""
    store, publisher = _services()
    try:
        record = store.get(event_id)
    except KeyError as exc:
        raise HTTPException(404, "Discord event not found") from exc
    except sqlite3.Error:
        raise HTTPException(503, "Discord event storage is unavailable") from None
    if record["approval_state"] != "approved" or record["delivery_status"] != "queued":
        raise HTTPException(409, "only approved queued events can be recovered")
    try:
        record = _deliver(store, publisher, record)
    except sqlite3.Error:
        raise HTTPException(503, "Discord event storage is unavailable") from None
    return JSONResponse(DiscordEventStore.public_record(record))


@router.post("/events/{event_id}/reconcile")
async def reconcile_ambiguous_discord_event(
    event_id: str,
    request: Request,
    operator: dict = Depends(require_permission("platform.manage_infra")),
) -> JSONResponse:
    """Record an operator-verified outcome; only verified non-delivery can replay."""
    try:
        payload = await request.json()
        outcome = payload.get("outcome") if isinstance(payload, dict) else None
        if outcome not in {"delivered", "not_delivered"}:
            raise HTTPException(422, "outcome must be delivered or not_delivered")
        record = store_from_env().reconcile_unknown(
            event_id, outcome=outcome, reconciled_by=str(operator.get("sub") or "unknown-operator"),
        )
    except KeyError as exc:
        raise HTTPException(404, "Discord event not found") from exc
    except DiscordEventConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, "invalid reconciliation outcome") from exc
    except sqlite3.Error:
        raise HTTPException(503, "Discord event storage is unavailable") from None
    return JSONResponse(DiscordEventStore.public_record(record))
