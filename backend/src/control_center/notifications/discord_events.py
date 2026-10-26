"""Authenticated Discord event ingestion and durable event records.

Source services authenticate with an HMAC over the exact request bytes. Human
approval and DLQ replay remain IAM-protected API operations in
``routes_discord_events.py``; a source signature alone never grants approval.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from control_center.notifications.discord import DiscordEvent, EVENT_ROUTES

SOURCE_EVENT_TYPES: dict[str, frozenset[str]] = {
    "github": frozenset({
        "platform.release", "platform.milestone", "github.issue.confirmed",
        "github.issue.resolved", "feature.request.accepted", "github.workflow.failed",
    }),
    "rag": frozenset({"support.incident", "support.resolved", "documentation.published"}),
    "workbench": frozenset({"support.incident", "support.resolved", "platform.release"}),
    "documentation": frozenset({"documentation.published", "infrastructure.alert"}),
    "video": frozenset({"video.published"}),
    "infrastructure": frozenset({"infrastructure.alert", "security.alert"}),
    "support": frozenset({"support.incident", "support.resolved", "feature.request.accepted"}),
}

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SOURCE = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
_NONCE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_HMAC_KEY = re.compile(r"^[A-Za-z0-9_-]{43,}$")
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_FORBIDDEN_FIELD_PARTS = {
    "email", "username", "user", "patient", "sample", "dataset", "filename",
    "filepath", "query", "prompt", "token", "secret", "password", "study",
}
_ALLOWED_COLORS = {"success", "error", "warning", "info"}


class DiscordEventValidationError(ValueError):
    pass


class DiscordSourceAuthError(ValueError):
    pass


class DiscordEventConflictError(ValueError):
    pass


class DiscordApprovalError(DiscordEventValidationError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_source_secrets(env: Mapping[str, str] | None = None) -> dict[str, tuple[str, ...]]:
    source = os.environ if env is None else env
    raw = source.get("DISCORD_EVENT_SOURCE_SECRETS", "").strip()
    parsed: dict[str, str | list[str]] = {}
    if raw:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DiscordSourceAuthError("DISCORD_EVENT_SOURCE_SECRETS must be a JSON object") from exc
        if not isinstance(value, dict):
            raise DiscordSourceAuthError("DISCORD_EVENT_SOURCE_SECRETS must be a JSON object")
        parsed.update(value)
    for name in SOURCE_EVENT_TYPES:
        value = source.get(f"DISCORD_EVENT_{name.upper()}_SECRET", "").strip()
        if value:
            parsed[name] = value
    result: dict[str, tuple[str, ...]] = {}
    for name, configured in parsed.items():
        keys = [configured] if isinstance(configured, str) else configured
        if name not in SOURCE_EVENT_TYPES or not isinstance(keys, list) or not 1 <= len(keys) <= 2:
            raise DiscordSourceAuthError("Discord event source authentication is invalid")
        if any(not isinstance(key, str) or not _HMAC_KEY.fullmatch(key) for key in keys):
            raise DiscordSourceAuthError("Discord event source authentication is invalid")
        result[name] = tuple(keys)
    for name in SOURCE_EVENT_TYPES:
        previous = source.get(f"DISCORD_EVENT_{name.upper()}_PREVIOUS_SECRET", "").strip()
        if previous:
            if not _HMAC_KEY.fullmatch(previous):
                raise DiscordSourceAuthError("Discord event source authentication is invalid")
            current = result.get(name)
            if not current or len(current) != 1:
                raise DiscordSourceAuthError("Discord event source rotation configuration is invalid")
            result[name] = (current[0], previous)
    owners: dict[str, str] = {}
    for name, keys in result.items():
        for key in keys:
            previous_owner = owners.get(key)
            if previous_owner is not None and previous_owner != name:
                raise DiscordSourceAuthError(
                    "Discord event source keys must be unique across source identities"
                )
            owners[key] = name
    return result


def load_approval_sources(env: Mapping[str, str] | None = None) -> dict[str, frozenset[str]]:
    """Deployment-authorized sources allowed to assert prior editorial approval."""
    source = os.environ if env is None else env
    raw = source.get("DISCORD_EVENT_APPROVAL_SOURCES", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DiscordSourceAuthError("DISCORD_EVENT_APPROVAL_SOURCES must be a JSON object") from exc
    if not isinstance(parsed, dict):
        raise DiscordSourceAuthError("DISCORD_EVENT_APPROVAL_SOURCES must be a JSON object")
    result = {}
    for name, event_types in parsed.items():
        if name not in SOURCE_EVENT_TYPES or not isinstance(event_types, list):
            raise DiscordSourceAuthError("Discord event approval policy is invalid")
        values = frozenset(str(value) for value in event_types)
        if not values.issubset(SOURCE_EVENT_TYPES[name]):
            raise DiscordSourceAuthError("Discord event approval policy is invalid")
        result[name] = values
    return result


def sign_request(secret: str, timestamp: str, nonce: str, body: bytes) -> str:
    message = timestamp.encode() + b"\n" + nonce.encode() + b"\n" + body
    return "v1=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_request_signature(
    *, source: str, timestamp: str, nonce: str, signature: str, body: bytes,
    secrets: Mapping[str, str | tuple[str, ...] | list[str]], now: float | None = None,
) -> None:
    if source not in SOURCE_EVENT_TYPES or not _SOURCE.fullmatch(source):
        raise DiscordSourceAuthError("unknown event source")
    secret = secrets.get(source)
    if not secret:
        raise DiscordSourceAuthError("event source is not configured")
    try:
        sent_at = int(timestamp)
    except (TypeError, ValueError) as exc:
        raise DiscordSourceAuthError("invalid event timestamp") from exc
    if abs((time.time() if now is None else now) - sent_at) > 300:
        raise DiscordSourceAuthError("expired event signature")
    if not _NONCE.fullmatch(nonce):
        raise DiscordSourceAuthError("invalid event nonce")
    candidates = (secret,) if isinstance(secret, str) else tuple(secret)
    # Evaluate every active key; do not early-exit on the matching rotation key.
    matched = False
    for candidate in candidates:
        matched = hmac.compare_digest(sign_request(candidate, timestamp, nonce, body), signature) | matched
    if not matched:
        raise DiscordSourceAuthError("invalid event signature")


def parse_event_payload(
    raw: bytes, *, authenticated_source: str,
    approval_sources: Mapping[str, frozenset[str]] | None = None,
) -> tuple[DiscordEvent, dict[str, Any]]:
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DiscordEventValidationError("request body must be valid JSON") from exc
    required = {
        "event_id", "event_type", "source_service", "created_at", "destination_channel",
        "approved_publication", "safe_message_payload", "correlation_id",
    }
    if not isinstance(data, dict) or set(data) != required:
        raise DiscordEventValidationError("event envelope has missing or unknown fields")
    event_id = data["event_id"]
    correlation_id = data["correlation_id"]
    event_type = data["event_type"]
    if not isinstance(event_id, str) or not _SAFE_ID.fullmatch(event_id):
        raise DiscordEventValidationError("invalid event_id")
    if not isinstance(correlation_id, str) or not _SAFE_ID.fullmatch(correlation_id):
        raise DiscordEventValidationError("invalid correlation_id")
    if data["source_service"] != authenticated_source:
        raise DiscordEventValidationError("source_service does not match authenticated source")
    if event_type not in SOURCE_EVENT_TYPES.get(authenticated_source, frozenset()):
        raise DiscordEventValidationError("event type is not authorized for this source")
    destination = EVENT_ROUTES.get(event_type)
    if destination is None or data["destination_channel"] != destination:
        raise DiscordEventValidationError("destination_channel does not match the configured route")
    try:
        created = datetime.fromisoformat(str(data["created_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise DiscordEventValidationError("created_at must be an ISO-8601 timestamp") from exc
    if created.tzinfo is None:
        raise DiscordEventValidationError("created_at must include a timezone")
    if created.timestamp() > time.time() + 300:
        raise DiscordEventValidationError("created_at is in the future")
    approved = data["approved_publication"]
    if not isinstance(approved, bool):
        raise DiscordEventValidationError("approved_publication must be a boolean")
    if approved and event_type not in (approval_sources or {}).get(authenticated_source, frozenset()):
        raise DiscordApprovalError("source is not authorized to assert publication approval")

    payload = data["safe_message_payload"]
    if not isinstance(payload, dict) or not set(payload).issubset({"title", "message", "color", "fields"}):
        raise DiscordEventValidationError("safe_message_payload is invalid")
    title, message = payload.get("title"), payload.get("message")
    color, fields = payload.get("color", "info"), payload.get("fields", {})
    if not isinstance(title, str) or not title.strip() or len(title) > 512:
        raise DiscordEventValidationError("safe title is invalid")
    if not isinstance(message, str) or not message.strip() or len(message) > 12000:
        raise DiscordEventValidationError("safe message is invalid")
    if color not in _ALLOWED_COLORS or not isinstance(fields, dict) or len(fields) > 25:
        raise DiscordEventValidationError("safe message formatting is invalid")
    if _EMAIL.search(title) or _EMAIL.search(message):
        raise DiscordEventValidationError("safe payload contains email-like PII")
    clean_fields: dict[str, object] = {}
    for key, value in fields.items():
        if not isinstance(key, str) or not isinstance(value, (str, int, float, bool)):
            raise DiscordEventValidationError("safe message field is invalid")
        normalized = re.sub(r"[^a-z]", "", key.lower())
        if any(part in normalized for part in _FORBIDDEN_FIELD_PARTS) or _EMAIL.search(str(value)):
            raise DiscordEventValidationError("safe payload contains a prohibited field")
        clean_fields[key] = value
    event = DiscordEvent(
        event_id=event_id, event_type=event_type, title=title, message=message,
        approved=approved, visibility="public", color=color, fields=clean_fields,
        source_service=authenticated_source, created_at=created.isoformat(),
        destination_channel=destination, correlation_id=correlation_id,
    )
    return event, data


class DiscordEventStore:
    """Versioned SQLite store for envelopes, state transitions, and replay nonces."""

    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.state_dir, 0o700)
        self.path = self.state_dir / "deliveries.sqlite3"
        self._migrate()
        os.chmod(self.path, 0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _migrate(self) -> None:
        migrations = {
            1: (
                """CREATE TABLE IF NOT EXISTS discord_event_records (
                    event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, source_service TEXT NOT NULL,
                    created_at TEXT NOT NULL, destination_channel TEXT NOT NULL,
                    approved_publication INTEGER NOT NULL, approval_state TEXT NOT NULL,
                    payload_json TEXT NOT NULL, correlation_id TEXT NOT NULL,
                    delivery_status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT, receipt_json TEXT, payload_sha256 TEXT NOT NULL,
                    approved_by TEXT, approved_at TEXT, updated_at REAL NOT NULL
                )""",
                """CREATE TABLE IF NOT EXISTS discord_event_nonces (
                    source_service TEXT NOT NULL, nonce TEXT NOT NULL, seen_at REAL NOT NULL,
                    PRIMARY KEY(source_service, nonce)
                )""",
            ),
            2: (
                "CREATE INDEX IF NOT EXISTS ix_discord_events_status ON discord_event_records(delivery_status)",
                "CREATE INDEX IF NOT EXISTS ix_discord_events_correlation ON discord_event_records(correlation_id)",
                "CREATE INDEX IF NOT EXISTS ix_discord_nonces_seen ON discord_event_nonces(seen_at)",
            ),
            3: (
                "ALTER TABLE discord_event_records ADD COLUMN reconciled_by TEXT",
                "ALTER TABLE discord_event_records ADD COLUMN reconciliation TEXT",
                "ALTER TABLE discord_event_records ADD COLUMN reconciled_at TEXT",
            ),
        }
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS discord_schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {row[0] for row in connection.execute("SELECT version FROM discord_schema_migrations")}
            for version, statements in migrations.items():
                if version in applied:
                    continue
                for statement in statements:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO discord_schema_migrations(version, applied_at) VALUES(?,?)",
                    (version, _now_iso()),
                )

    def consume_nonce(self, source: str, nonce: str, *, now: float | None = None) -> None:
        stamp = time.time() if now is None else now
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM discord_event_nonces WHERE seen_at < ?", (stamp - 600,))
            try:
                connection.execute(
                    "INSERT INTO discord_event_nonces(source_service,nonce,seen_at) VALUES(?,?,?)",
                    (source, nonce, stamp),
                )
            except sqlite3.IntegrityError as exc:
                raise DiscordSourceAuthError("replayed event request") from exc

    def ingest(self, event: DiscordEvent, envelope: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        payload_json = _canonical_json(envelope)
        digest = hashlib.sha256(payload_json.encode()).hexdigest()
        state = "approved" if event.approved else "pending"
        status = "queued" if event.approved else "pending_approval"
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM discord_event_records WHERE event_id=?", (event.event_id,)
            ).fetchone()
            if row:
                if row["payload_sha256"] != digest:
                    raise DiscordEventConflictError("event_id already exists with different content")
                return dict(row), True
            connection.execute(
                """INSERT INTO discord_event_records(
                    event_id,event_type,source_service,created_at,destination_channel,
                    approved_publication,approval_state,payload_json,correlation_id,
                    delivery_status,payload_sha256,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event.event_id, event.event_type, event.source_service, event.created_at,
                 event.destination_channel, int(event.approved), state, payload_json,
                 event.correlation_id, status, digest, time.time()),
            )
        return self.get(event.event_id), False

    def get(self, event_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM discord_event_records WHERE event_id=?", (event_id,)
            ).fetchone()
        if row is None:
            raise KeyError(event_id)
        return dict(row)

    def list_events(self, *, status: str = "pending_approval", limit: int = 100) -> list[dict[str, Any]]:
        allowed = {"pending_approval", "queued", "delivering", "delivery_unknown", "failed", "delivered"}
        if status not in allowed or not 1 <= limit <= 500:
            raise ValueError("invalid event query")
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT * FROM discord_event_records WHERE delivery_status=? ORDER BY updated_at LIMIT ?",
                (status, limit),
            ).fetchall()
        return [self.public_record(dict(row)) for row in rows]

    def recover_inflight(self, *, now: float | None = None, lease_seconds: float = 60) -> int:
        """Classify stale in-flight sends as ambiguous; never retry them blindly."""
        stamp = time.time() if now is None else now
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """UPDATE discord_event_records SET delivery_status='delivery_unknown',
                   last_error='delivery outcome requires operator reconciliation', updated_at=?
                   WHERE delivery_status='delivering' AND updated_at < ?""",
                (stamp, stamp - max(1.0, lease_seconds)),
            )
            return cursor.rowcount

    def sync_confirmed_deliveries(self) -> int:
        """Promote events only when the adjacent durable publisher ledger says 2xx."""
        with closing(self._connect()) as connection, connection:
            try:
                rows = connection.execute(
                    """SELECT event_id, attempts, status FROM discord_deliveries WHERE status IN ('delivered','failed','unknown')
                       AND event_id IN (SELECT event_id FROM discord_event_records WHERE delivery_status='delivering')"""
                ).fetchall()
            except sqlite3.OperationalError:
                # A fresh event-store-only test or old deployment before the
                # V1 publisher table exists has no delivery receipts to sync.
                return 0
            for row in rows:
                state_to_status = {"delivered": "delivered", "failed": "failed", "unknown": "delivery_unknown"}
                event_status = state_to_status[str(row[2])]
                receipt = _canonical_json({
                    "event_id": row[0], "status": event_status, "attempts": row[1],
                    "recorded_at": _now_iso(), "recovered_from_local_receipt": True,
                })
                connection.execute(
                    """UPDATE discord_event_records SET delivery_status=?, attempts=?,
                       last_error=?, receipt_json=?, updated_at=? WHERE event_id=? AND delivery_status='delivering'""",
                    (event_status, row[1], None if event_status == "delivered" else "recovered local delivery state",
                     receipt, time.time(), row[0]),
                )
            return len(rows)

    def reconcile_unknown(self, event_id: str, *, outcome: str, reconciled_by: str) -> dict[str, Any]:
        if outcome not in {"delivered", "not_delivered"}:
            raise ValueError("outcome must be delivered or not_delivered")
        status = "delivered" if outcome == "delivered" else "failed"
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT delivery_status, attempts FROM discord_event_records WHERE event_id=?", (event_id,)
            ).fetchone()
            if row is None:
                raise KeyError(event_id)
            if row[0] != "delivery_unknown":
                raise DiscordEventConflictError("only ambiguous deliveries can be reconciled")
            receipt = _canonical_json({
                "event_id": event_id, "status": status, "attempts": row[1],
                "reconciled_by": reconciled_by, "reconciliation": outcome, "recorded_at": _now_iso(),
            })
            connection.execute(
                """UPDATE discord_event_records SET delivery_status=?, last_error=NULL, receipt_json=?,
                   reconciled_by=?, reconciliation=?, reconciled_at=?, updated_at=? WHERE event_id=?""",
                (status, receipt, reconciled_by, outcome, _now_iso(), time.time(), event_id),
            )
        return self.get(event_id)

    def approve(self, event_id: str, approved_by: str) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT approval_state FROM discord_event_records WHERE event_id=?", (event_id,)
            ).fetchone()
            if row is None:
                raise KeyError(event_id)
            if row[0] == "rejected":
                raise DiscordEventConflictError("rejected event cannot be approved")
            connection.execute(
                """UPDATE discord_event_records SET approved_publication=1, approval_state='approved',
                   approved_by=?, approved_at=?, delivery_status='queued', updated_at=? WHERE event_id=?""",
                (approved_by, _now_iso(), time.time(), event_id),
            )
        return self.get(event_id)

    def update_delivery(self, event_id: str, *, status: str, attempts: int, error: str | None = None) -> dict[str, Any]:
        receipt = _canonical_json({
            "event_id": event_id, "status": status, "attempts": attempts, "recorded_at": _now_iso(),
        })
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """UPDATE discord_event_records SET delivery_status=?, attempts=?, last_error=?,
                   receipt_json=?, updated_at=? WHERE event_id=?""",
                (status, attempts, error, receipt, time.time(), event_id),
            )
        return self.get(event_id)

    @staticmethod
    def event_from_record(record: Mapping[str, Any]) -> DiscordEvent:
        envelope = json.loads(record["payload_json"])
        payload = envelope["safe_message_payload"]
        return DiscordEvent(
            event_id=record["event_id"], event_type=record["event_type"],
            title=payload["title"], message=payload["message"], approved=True,
            color=payload.get("color", "info"), fields=payload.get("fields", {}),
            source_service=record["source_service"], created_at=record["created_at"],
            destination_channel=record["destination_channel"], correlation_id=record["correlation_id"],
        )

    @staticmethod
    def public_record(record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: record.get(key) for key in (
                "event_id", "event_type", "source_service", "created_at", "destination_channel",
                "approval_state", "correlation_id", "delivery_status", "attempts",
                "approved_by", "approved_at",
                "reconciled_by", "reconciliation", "reconciled_at",
            )
        }


def store_from_env(env: Mapping[str, str] | None = None) -> DiscordEventStore:
    source = os.environ if env is None else env
    return DiscordEventStore(source.get("DISCORD_DELIVERY_STATE_DIR", "work/discord"))
