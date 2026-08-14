"""HIPAA Basic Compliance Report v0.8.0: audit trail for the report
feature's own usage. Reuses the existing `audit:events` Redis stream --
the same platform-wide, multi-writer event bus omnibioai-security-audit's
consumer already drains into its durable `audit_events` table, and that
omnibioai-api-gateway's own middleware (AuthMiddleware/PolicyMiddleware/
HpcMiddleware/AuditMiddleware -- see checks/gateway_traffic.py's own
comment for that inventory) already writes to. This module makes
control-center one more writer into infrastructure that already exists;
it does not add a new stream, a new consumer, or a new persistence
table. The event shape below matches omnibioai-security-audit's own
AuditEvent pydantic model (audit/models.py) field-for-field, so if/when
that service's consumer processes this stream, an event written here
persists as a normal, queryable AuditEventRecord row through the
existing GET /audit/events API -- no changes needed on that side.

Pre-merge security review finding (2026-08-12): "generating a HIPAA
compliance report is itself a sensitive administrative action that isn't
currently recorded anywhere" -- this module is that record. Called from
router.py after each of the three endpoints successfully builds its
response (JSON/PDF/CSV) -- never on a 401/403/404, which have nothing to
record here.

Best-effort, fire-and-forget, synchronous: matches the exact posture
every other audit-write call site in this platform documents for itself
(omnibioai-security-audit's AuditLogger.log(), omnibioai-auth's
audit_service.log_event -- both "NEVER break core system", swallow and
log a warning rather than raise). Synchronous, not async, matching
analytics/cache.py's own established pattern of doing a single blocking
Redis call from inside an async route handler -- a single XADD is fast
enough that a dedicated async Redis client would be new-pattern
complexity this module doesn't need.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import uuid
from datetime import date, datetime, timezone

import redis

from control_center.core.jwt_verify import JWT_SECRET

logger = logging.getLogger("control_center.compliance.audit_log")

# Same env var names/defaults omnibioai-security-audit's own
# AuditConfig uses (audit/config.py) -- not redefined independently, so
# a deployment that already points AUDIT_STREAM/AUDIT_MAXLEN somewhere
# non-default for that service doesn't need a second, possibly-drifting
# set of env vars here.
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
AUDIT_STREAM = os.environ.get("AUDIT_STREAM", "audit:events")
MAX_STREAM_LENGTH = int(os.environ.get("AUDIT_MAXLEN", "1000000"))

_redis = redis.from_url(REDIS_URL, decode_responses=True)


# ---------------------------------------------------------------------------
# HIPAA PR3b: producer-side signing. Hand-ported from
# omnibioai-security-audit's audit/signing.py::sign_audit_event -- not a
# shared import (that repo is not a dependency of this one, same tradeoff
# already documented at the top of this module for the event-shape
# mirroring above).
# ---------------------------------------------------------------------------
_SIGNING_DOMAIN_LABEL = "omnibioai-audit-events"
_SIGNING_VERSION = "v1"


def _signing_key(secret: str) -> bytes:
    return hashlib.sha256(f"{_SIGNING_DOMAIN_LABEL}:{secret}".encode()).digest()


def _signing_message(version: str, service: str, data: str) -> bytes:
    return f"{version}\n{service}\n{data}".encode()


def sign_audit_event(service: str, data: str, secret: str) -> str:
    """Returns the `sig` field value for one audit event: `"v1:<hex-hmac>"`.

    `data` must be the *exact* string written to the stream's `data`
    field -- not a re-serialization. See log_report_access() below.
    """
    if not service:
        raise ValueError("service must be a non-empty string")
    if data is None:
        raise ValueError("data must not be None")
    mac = hmac.new(
        _signing_key(secret), _signing_message(_SIGNING_VERSION, service, data), hashlib.sha256
    ).hexdigest()
    return f"{_SIGNING_VERSION}:{mac}"


def log_report_access(
    *, actor: str, organization_id: int, from_date: date, to_date: date, report_format: str,
) -> None:
    """Records one "a platform_admin generated/downloaded a HIPAA
    compliance report" event. `actor` is the same email/sub value
    router.py already resolves as generated_by -- not re-derived here,
    so this module never touches the JWT itself.
    """
    event = {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "control-center",
        "event_type": "compliance_report_accessed",
        "user_id": actor,
        "action": "generate",
        "resource": f"organization:{organization_id}",
        "decision": "success",
        "reason": None,
        "trace_id": None,
        "context": {
            "organization_id": organization_id,
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "format": report_format,
        },
    }
    try:
        data = json.dumps(event)
        fields = {"data": data}
        fields["sig"] = sign_audit_event(event["service"], data, JWT_SECRET)
        _redis.xadd(AUDIT_STREAM, fields, maxlen=MAX_STREAM_LENGTH, approximate=True)
    except Exception:
        # Never let an audit-logging failure break the actual report
        # response that already succeeded -- see this module's own
        # docstring.
        logger.warning("compliance_report_audit_log_failed", exc_info=True)
