"""Secure, event-driven Discord publishing for OmniBioAI.

The legacy :func:`notify` entry point remains for existing health checks. New
publishers should emit a :class:`DiscordEvent` through :class:`DiscordPublisher`.
Webhook values are never returned, logged, or written to the dead-letter file.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import os
import re
import secrets
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

import httpx
from prometheus_client import Counter

DISCORD_COLORS = {
    "success": 0x00D4AA,
    "error": 0xE24B4A,
    "warning": 0xF59E0B,
    "info": 0x7C3AED,
}

# All nine community channels are listed intentionally. The three with no
# routes stay community-driven and cannot be selected by an automated event.
COMMUNITY_CHANNELS = (
    "general", "announcements", "research-chat", "show-and-tell",
    "bug-reports", "feature-requests", "support", "tutorials",
    "omnibioai-alerts",
)

EVENT_ROUTES = {
    "platform.release": "announcements",
    "platform.milestone": "announcements",
    "github.issue.confirmed": "bug-reports",
    "github.issue.resolved": "bug-reports",
    "feature.request.accepted": "feature-requests",
    "support.incident": "support",
    "support.resolved": "support",
    "documentation.published": "tutorials",
    "video.published": "tutorials",
    "infrastructure.alert": "omnibioai-alerts",
    "security.alert": "omnibioai-alerts",
    "github.workflow.failed": "omnibioai-alerts",
}

AUTOMATED_CHANNELS = frozenset(EVENT_ROUTES.values())
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")  # legacy import
_WEBHOOK_PATH = re.compile(r"^/api(?:/v\d+)?/webhooks/(?P<webhook_id>[0-9]+)/[^/]+/?$")
_SECRET_URL = re.compile(
    r"https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api(?:/v\d+)?/webhooks/[^\s\"']+",
    re.I,
)
_EVENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_LOGGER = logging.getLogger("control_center.notifications.discord")

DELIVERIES = Counter(
    "discord_channel_deliveries_total",
    "Discord delivery outcomes by destination channel",
    ("channel", "status"),
)
RETRIES = Counter(
    "discord_channel_retries_total",
    "Discord delivery retries by destination channel",
    ("channel", "reason"),
)


class DiscordConfigError(ValueError):
    """A channel map is malformed or contains an unsafe webhook endpoint."""


def _redact(value: object) -> str:
    """Remove Discord webhook credentials from an exception or log value."""
    return _SECRET_URL.sub("[REDACTED_DISCORD_WEBHOOK]", str(value))


def _validate_webhook(url: str, channel: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError as exc:
        raise DiscordConfigError(f"invalid Discord webhook configuration for channel {channel!r}") from exc
    if (
        parts.scheme != "https"
        or parts.username is not None
        or parts.password is not None
        or host not in {"discord.com", "discordapp.com", "canary.discord.com", "ptb.discord.com"}
        or port not in {None, 443}
        or not _WEBHOOK_PATH.fullmatch(parts.path)
        or parts.query
        or parts.fragment
    ):
        raise DiscordConfigError(f"invalid Discord webhook configuration for channel {channel!r}")
    return url


def _validate_distinct_webhooks(webhooks: Mapping[str, str]) -> None:
    """Reject channel maps that alias multiple routes to one Discord webhook."""
    owners: dict[str, str] = {}
    for channel, url in webhooks.items():
        match = _WEBHOOK_PATH.fullmatch(urlsplit(url).path)
        # _validate_webhook has already checked the path; keep this defensive
        # so callers cannot bypass endpoint validation through this helper.
        if match is None:
            raise DiscordConfigError(f"invalid Discord webhook configuration for channel {channel!r}")
        webhook_id = match.group("webhook_id")
        previous = owners.get(webhook_id)
        if previous is not None:
            raise DiscordConfigError(
                f"Discord channels {previous!r} and {channel!r} use the same webhook destination"
            )
        owners[webhook_id] = channel


def load_channel_webhooks(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Load the secret JSON map and the legacy alerts migration fallback."""
    source = os.environ if env is None else env
    raw = source.get("DISCORD_CHANNEL_WEBHOOKS", "").strip()
    values: dict[str, Any] = {}
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DiscordConfigError("DISCORD_CHANNEL_WEBHOOKS must be a JSON object") from exc
        if not isinstance(parsed, dict):
            raise DiscordConfigError("DISCORD_CHANNEL_WEBHOOKS must be a JSON object")
        values.update(parsed)

    legacy_alert = source.get("DISCORD_ALERT_WEBHOOK_URL", "").strip()
    legacy_alert_id: str | None = None
    if legacy_alert:
        legacy_alert = _validate_webhook(legacy_alert, "omnibioai-alerts")
        legacy_match = _WEBHOOK_PATH.fullmatch(urlsplit(legacy_alert).path)
        assert legacy_match is not None  # guaranteed by _validate_webhook
        legacy_alert_id = legacy_match.group("webhook_id")
        values.setdefault("omnibioai-alerts", legacy_alert)

    result: dict[str, str] = {}
    for channel, value in values.items():
        if channel not in COMMUNITY_CHANNELS:
            raise DiscordConfigError(f"unknown Discord channel {channel!r}")
        if channel not in AUTOMATED_CHANNELS:
            raise DiscordConfigError(f"channel {channel!r} is community-driven and cannot be automated")
        if not isinstance(value, str) or not value.strip():
            raise DiscordConfigError(f"missing Discord webhook configuration for channel {channel!r}")
        result[channel] = _validate_webhook(value.strip(), channel)
    if legacy_alert_id is not None:
        for channel, url in result.items():
            match = _WEBHOOK_PATH.fullmatch(urlsplit(url).path)
            assert match is not None  # each map value was validated above
            if channel != "omnibioai-alerts" and match.group("webhook_id") == legacy_alert_id:
                raise DiscordConfigError(
                    f"legacy alerts webhook aliases the {channel!r} channel destination"
                )
    _validate_distinct_webhooks(result)
    return result


def channel_configuration_status(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return names/statuses only; credential material is never exposed."""
    configured = load_channel_webhooks(env)
    return {
        channel: (
            "configured" if channel in configured else
            "community-driven" if channel not in AUTOMATED_CHANNELS else "missing"
        )
        for channel in COMMUNITY_CHANNELS
    }


def _safe_text(value: object, limit: int) -> str:
    text = str(value).replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")
    text = text.replace("<@&", "<@\u200b&").replace("<@", "<@\u200b").replace("<#", "<#\u200b")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


@dataclass(frozen=True)
class DiscordEvent:
    event_id: str
    event_type: str
    title: str
    message: str
    approved: bool = False
    visibility: str = "public"
    color: str = "info"
    fields: Mapping[str, object] = field(default_factory=dict)
    source_service: str = "legacy"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    destination_channel: str | None = None
    correlation_id: str = ""


@dataclass(frozen=True)
class DeliveryResult:
    status: str
    event_id: str
    channel: str | None = None
    attempts: int = 0


class DiscordPublisher:
    """Synchronous event publisher with persistent idempotency and a DLQ."""

    def __init__(
        self,
        webhooks: Mapping[str, str],
        *,
        state_dir: str | Path = "work/discord",
        max_attempts: int = 4,
        base_backoff: float = 0.5,
        max_backoff: float = 8.0,
        post: Callable[..., Any] = httpx.post,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not 1 <= max_attempts <= 8:
            raise DiscordConfigError("max_attempts must be between 1 and 8")
        self.webhooks = {name: _validate_webhook(url, name) for name, url in webhooks.items()}
        unknown = set(self.webhooks) - AUTOMATED_CHANNELS
        if unknown:
            raise DiscordConfigError(f"unroutable Discord channels: {sorted(unknown)!r}")
        _validate_distinct_webhooks(self.webhooks)
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.state_dir, 0o700)
        self.db_path = self.state_dir / "deliveries.sqlite3"
        self.dlq_path = self.state_dir / "dead-letter.jsonl"
        self.max_attempts = max_attempts
        self.base_backoff = max(0.0, base_backoff)
        self.max_backoff = max(0.0, max_backoff)
        self._post = post
        self._sleep = sleep
        self._initialize_store()
        os.chmod(self.db_path, 0o600)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, **kwargs: Any) -> "DiscordPublisher":
        source = os.environ if env is None else env
        return cls(
            load_channel_webhooks(source),
            state_dir=source.get("DISCORD_DELIVERY_STATE_DIR", "work/discord"),
            **kwargs,
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=5)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize_store(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS discord_deliveries (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL
                )"""
            )

    def _claim(self, event: DiscordEvent, channel: str, *, replay: bool = False) -> bool:
        now = time.time()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, updated_at FROM discord_deliveries WHERE event_id = ?", (event.event_id,)
            ).fetchone()
            if row:
                if row[0] == "delivered":
                    return False
                if row[0] == "failed" and not replay:
                    return False
                if row[0] == "pending":
                    if now - float(row[1]) < 300:
                        return False
                    if replay:
                        # A manage-infra replay is the explicit operator
                        # decision made after reconciling the central event.
                        pass
                    else:
                        # A crashed process may have stopped before, during,
                        # or after Discord accepted the request. The ledger
                        # cannot distinguish those cases, so never reclaim it.
                        connection.execute(
                            "UPDATE discord_deliveries SET status='unknown', updated_at=? WHERE event_id=?",
                            (now, event.event_id),
                        )
                        return False
                if row[0] == "unknown" and not replay:
                    return False
            connection.execute(
                """INSERT INTO discord_deliveries(event_id,event_type,channel,status,attempts,updated_at)
                   VALUES(?,?,?,?,0,?)
                   ON CONFLICT(event_id) DO UPDATE SET status='pending', updated_at=excluded.updated_at""",
                (event.event_id, event.event_type, channel, "pending", now),
            )
        return True

    def _finish(self, event_id: str, status: str, attempts: int) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "UPDATE discord_deliveries SET status=?, attempts=?, updated_at=? WHERE event_id=?",
                (status, attempts, time.time(), event_id),
            )

    def delivery_state(self, event_id: str) -> tuple[str, int] | None:
        """Return the durable local claim state without payload or credential data."""
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT status, attempts FROM discord_deliveries WHERE event_id=?", (event_id,)
            ).fetchone()
        return (str(row[0]), int(row[1])) if row else None

    @staticmethod
    def _payload(event: DiscordEvent) -> dict[str, Any]:
        title = _safe_text(event.title, 256)
        footer = "OmniBioAI"
        remaining = 6000 - len(title) - len(footer)
        description = _safe_text(event.message, min(4096, max(1, remaining)))
        remaining -= len(description)
        fields = []
        for key, value in list(event.fields.items())[:25]:
            if remaining < 2:
                break
            name = _safe_text(key, min(256, remaining - 1))
            remaining -= len(name)
            field_value = _safe_text(value, min(1024, max(1, remaining)))
            remaining -= len(field_value)
            fields.append({"name": name, "value": field_value, "inline": True})
        embed: dict[str, Any] = {
            "title": title,
            "description": description,
            "color": DISCORD_COLORS.get(event.color, DISCORD_COLORS["info"]),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": footer},
        }
        if fields:
            embed["fields"] = fields
        return {
            "username": "OmniBioAI",
            "allowed_mentions": {"parse": [], "replied_user": False},
            "embeds": [embed],
        }

    def _retry_delay(self, response: Any, attempt: int) -> float:
        header = getattr(response, "headers", {}).get("Retry-After")
        try:
            value = float(header) if header is not None else None
        except (TypeError, ValueError):
            value = None
        if value is not None and not math.isfinite(value):
            value = None
        if value is None:
            try:
                value = float(response.json().get("retry_after"))
            except (AttributeError, TypeError, ValueError):
                value = None
        if value is None:
            value = self.base_backoff * (2 ** (attempt - 1))
        return min(max(0.0, value), self.max_backoff)

    def _dead_letter(self, event: DiscordEvent, channel: str, attempts: int, error: object) -> None:
        record = {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "channel": channel,
            "attempts": attempts,
            "error": _redact(error),
            "payload_sha256": hashlib.sha256(
                json.dumps(self._payload(event), sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }
        descriptor = os.open(self.dlq_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.chmod(self.dlq_path, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")

    def publish(self, event: DiscordEvent, *, replay: bool = False) -> DeliveryResult:
        channel = EVENT_ROUTES.get(event.event_type)
        if channel is None:
            return DeliveryResult("filtered", event.event_id)
        if not event.approved or event.visibility != "public":
            DELIVERIES.labels(channel, "filtered").inc()
            return DeliveryResult("filtered", event.event_id, channel)
        if event.destination_channel is not None and event.destination_channel != channel:
            raise ValueError("event destination_channel does not match the configured route")
        webhook = self.webhooks.get(channel)
        if not webhook:
            DELIVERIES.labels(channel, "not_configured").inc()
            return DeliveryResult("not_configured", event.event_id, channel)
        if not _EVENT_ID.fullmatch(event.event_id):
            raise ValueError("event_id must use only letters, digits, dot, underscore, colon, or hyphen")
        if not self._claim(event, channel, replay=replay):
            DELIVERIES.labels(channel, "duplicate").inc()
            state = self.delivery_state(event.event_id)
            if state and state[0] == "unknown":
                DELIVERIES.labels(channel, "delivery_unknown").inc()
                return DeliveryResult("delivery_unknown", event.event_id, channel, state[1])
            return DeliveryResult("duplicate", event.event_id, channel)

        payload = self._payload(event)
        attempts = 0
        last_error: object = "delivery failed"
        for attempts in range(1, self.max_attempts + 1):
            try:
                response = self._post(webhook, params={"wait": "true"}, json=payload, timeout=5)
                status = int(response.status_code)
                if 200 <= status < 300:
                    self._finish(event.event_id, "delivered", attempts)
                    DELIVERIES.labels(channel, "delivered").inc()
                    _LOGGER.info(
                        "discord delivery succeeded",
                        extra={"extra_fields": {"channel": channel, "event_id": event.event_id}},
                    )
                    return DeliveryResult("delivered", event.event_id, channel, attempts)
                last_error = f"Discord returned HTTP {status}"
                if 500 <= status < 600:
                    # A 5xx may have happened after Discord accepted the POST.
                    # Without an upstream idempotency key, never blind-retry it.
                    self._finish(event.event_id, "unknown", attempts)
                    self._dead_letter(event, channel, attempts, last_error)
                    DELIVERIES.labels(channel, "delivery_unknown").inc()
                    _LOGGER.warning("discord delivery outcome is ambiguous", extra={
                        "extra_fields": {"channel": channel, "event_id": event.event_id, "attempts": attempts},
                    })
                    return DeliveryResult("delivery_unknown", event.event_id, channel, attempts)
                retryable = status == 429
                reason = "rate_limit"
                if not retryable:
                    break
                delay = self._retry_delay(response, attempts)
            except (httpx.ConnectTimeout, httpx.ConnectError) as exc:
                last_error = exc.__class__.__name__
                reason = "network"
                delay = min(self.base_backoff * (2 ** (attempts - 1)), self.max_backoff)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc.__class__.__name__
                self._finish(event.event_id, "unknown", attempts)
                self._dead_letter(event, channel, attempts, last_error)
                DELIVERIES.labels(channel, "delivery_unknown").inc()
                _LOGGER.warning("discord delivery outcome is ambiguous", extra={
                    "extra_fields": {"channel": channel, "event_id": event.event_id, "attempts": attempts},
                })
                return DeliveryResult("delivery_unknown", event.event_id, channel, attempts)
            except Exception as exc:  # defensive isolation for custom transports
                last_error = type(exc).__name__
                self._finish(event.event_id, "unknown", attempts)
                self._dead_letter(event, channel, attempts, last_error)
                DELIVERIES.labels(channel, "delivery_unknown").inc()
                _LOGGER.warning("discord delivery outcome is ambiguous", extra={
                    "extra_fields": {"channel": channel, "event_id": event.event_id, "attempts": attempts},
                })
                return DeliveryResult("delivery_unknown", event.event_id, channel, attempts)
            if attempts < self.max_attempts:
                RETRIES.labels(channel, reason).inc()
                self._sleep(delay)

        self._finish(event.event_id, "failed", attempts)
        self._dead_letter(event, channel, attempts, last_error)
        DELIVERIES.labels(channel, "failed").inc()
        _LOGGER.warning(
            "discord delivery failed",
            extra={"extra_fields": {
                "channel": channel,
                "event_id": event.event_id,
                "attempts": attempts,
                "error": _redact(last_error),
            }},
        )
        return DeliveryResult("failed", event.event_id, channel, attempts)


def notify(
    webhook_url: str,
    title: str,
    message: str,
    color: str = "info",
    fields: dict | None = None,
    *,
    event_id: str | None = None,
) -> bool:
    """Centralize legacy alerts; require explicit opt-in for direct fallback.

    The central path submits a fixed, sanitized, unapproved alert for normal
    Control Center review. It never falls back to direct delivery after an
    attempted central submission, which prevents cross-path duplicates. When
    central routing is absent, direct webhook publication is disabled unless
    ``DISCORD_LEGACY_WEBHOOK_FALLBACK=enabled`` is explicitly set.
    """
    router_url = os.environ.get("DISCORD_EVENT_ROUTER_URL", "").strip()
    source_secret = os.environ.get("DISCORD_EVENT_INFRASTRUCTURE_SECRET", "").strip()
    if router_url or source_secret:
        if not router_url or not source_secret:
            _LOGGER.warning("central Discord alert configuration is incomplete", extra={
                "extra_fields": {"reason": "incomplete_router_configuration"},
            })
            return False
        return _submit_legacy_alert(router_url, source_secret, event_id or _legacy_event_id(title, message))
    if os.environ.get("DISCORD_LEGACY_WEBHOOK_FALLBACK", "").strip().lower() != "enabled":
        _LOGGER.warning("legacy Discord fallback is disabled", extra={
            "extra_fields": {"reason": "central_router_not_configured"},
        })
        return False
    if not webhook_url:
        return False
    try:
        webhook_url = _validate_webhook(webhook_url, "legacy")
    except DiscordConfigError:
        _LOGGER.warning("legacy Discord fallback rejected", extra={
            "extra_fields": {"reason": "invalid_discord_webhook"},
        })
        return False
    event = DiscordEvent("legacy", "legacy", title, message, True, fields=fields or {}, color=color)
    try:
        response = httpx.post(webhook_url, json=DiscordPublisher._payload(event), timeout=5)
        response.raise_for_status()
        return True
    except Exception as exc:
        _LOGGER.warning(
            "legacy Discord notify failed",
            extra={"extra_fields": {"error": _redact(exc)}},
        )
        return False


def _legacy_event_id(title: str, message: str) -> str:
    """Stable five-minute fallback identity; callers should supply an incident ID."""
    digest = hashlib.sha256(f"{title}\n{message}".encode()).hexdigest()[:32]
    return f"legacy-alert:{int(time.time() // 300)}:{digest}"


def _submit_legacy_alert(router_url: str, secret: str, event_id: str) -> bool:
    if not _EVENT_ID.fullmatch(event_id):
        _LOGGER.warning("central Discord alert rejected", extra={"extra_fields": {"reason": "invalid_event_id"}})
        return False
    if len(secret) < 43 or not secret.isascii() or not secret.replace("-", "").replace("_", "").isalnum():
        _LOGGER.warning("central Discord alert rejected", extra={"extra_fields": {"reason": "invalid_source_key"}})
        return False
    parts = urlsplit(router_url)
    if (
        parts.scheme not in {"https", "http"} or parts.username or parts.password
        or parts.query or parts.fragment
        or (parts.scheme == "http" and parts.hostname not in {"control-center", "localhost", "127.0.0.1"})
    ):
        _LOGGER.warning("central Discord alert rejected", extra={"extra_fields": {"reason": "invalid_router_url"}})
        return False
    envelope = {
        "event_id": event_id, "event_type": "infrastructure.alert",
        "source_service": "infrastructure", "created_at": datetime.now(timezone.utc).isoformat(),
        "destination_channel": "omnibioai-alerts", "approved_publication": False,
        "safe_message_payload": {
            "title": "OmniBioAI operational alert",
            "message": "A sanitized operational alert was reported by a trusted monitor. Review details in Control Center.",
            "color": "warning", "fields": {},
        },
        "correlation_id": event_id,
    }
    body = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    endpoint = router_url.rstrip("/") + "/integrations/discord/events"
    for attempt in range(1, 4):
        timestamp = str(int(time.time()))
        nonce = secrets.token_urlsafe(18)
        signed = timestamp.encode() + b"\n" + nonce.encode() + b"\n" + body
        signature = "v1=" + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        try:
            response = httpx.post(endpoint, content=body, timeout=5, headers={
                "Content-Type": "application/json", "X-Omni-Discord-Source": "infrastructure",
                "X-Omni-Discord-Timestamp": timestamp, "X-Omni-Discord-Nonce": nonce,
                "X-Omni-Discord-Signature": signature,
            })
            if response.status_code in {200, 202}:
                _LOGGER.info("central Discord alert accepted for review", extra={
                    "extra_fields": {"event_id": event_id, "attempt": attempt},
                })
                return True
            if response.status_code != 429 and response.status_code < 500:
                _LOGGER.warning("central Discord alert rejected", extra={
                    "extra_fields": {"event_id": event_id, "status": response.status_code},
                })
                return False
            if response.status_code == 429:
                try:
                    delay = float(response.headers.get("Retry-After", ""))
                except (TypeError, ValueError):
                    delay = 0.5 * (2 ** (attempt - 1))
                if not math.isfinite(delay):
                    delay = 0.5 * (2 ** (attempt - 1))
                delay = min(max(0.0, delay), 4.0)
            else:
                # Event-ID idempotency makes retry safe even if an upstream
                # 5xx occurred after the event record was committed.
                delay = 0.5 * (2 ** (attempt - 1))
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            delay = 0.5 * (2 ** (attempt - 1))
            _LOGGER.warning("central Discord alert transport failed", extra={
                "extra_fields": {"event_id": event_id, "error_type": type(exc).__name__, "attempt": attempt},
            })
        if attempt < 3:
            time.sleep(min(max(delay, 0.0), 4.0))
    return False
