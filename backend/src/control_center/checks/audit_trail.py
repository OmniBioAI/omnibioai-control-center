from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import os
from typing import Any, Optional

from control_center.core.jwt_verify import JWT_SECRET

# Same Redis instance + stream as checks/gateway_traffic.py (same audit_client
# writers -- api-gateway's AuthMiddleware/PolicyMiddleware/HpcMiddleware/
# AuditMiddleware). Reusing AUDIT_REDIS rather than a second env var since
# it's the identical connection.
AUDIT_REDIS = os.environ.get("AUDIT_REDIS", "redis://redis:6379")

# ---------------------------------------------------------------------------
# HIPAA PR3c: local signature verification for this endpoint only.
#
# security-audit's own GET /audit/events (PR #9, still open at the time of
# writing) exposes integrity_status, but has no event-ID/batch lookup --
# only coarse service/event_type/decision/time-range filters, capped at
# page_size=100. This endpoint's own 7-day window covers ~71,000 real
# events (measured against the live stack), so paging through that API to
# annotate every event here would take on the order of 700+ requests per
# dashboard load, or silently truncate the aggregate breakdowns below to a
# fraction of the real window -- neither preserves this function's
# existing contract. Verifying locally avoids that: it's a pure,
# per-event HMAC check with no new I/O and no new failure mode.
#
# Hand-ported from omnibioai-security-audit's audit/signing.py
# (sign_audit_event/verify_audit_event) -- not a shared import, the same
# tradeoff every other producer already accepted for this exact
# construction (api-gateway/tes/workflow-bundles/rag/control-center's own
# compliance/audit_log.py all keep their own copy of the signing half;
# this is the verification half, kept in its own copy for the same
# reason). Byte-for-byte identical: domain-separated HMAC-SHA256 key
# derivation, "v1\n<service>\n<data>" as the signed message. Must stay in
# sync with audit/signing.py or every event this function checks will be
# misclassified -- see test_check_audit_trail.py's own cross-repo vector
# test for the drift-detection mechanism the other five hand-ports
# already use.
# ---------------------------------------------------------------------------
_SIGNING_DOMAIN_LABEL = "omnibioai-audit-events"
_SIGNING_VERSION = "v1"


def _signing_key(secret: str) -> bytes:
    return hashlib.sha256(f"{_SIGNING_DOMAIN_LABEL}:{secret}".encode()).digest()


def _signing_message(version: str, service: str, data: str) -> bytes:
    return f"{version}\n{service}\n{data}".encode()


def verify_audit_event(service: str, data: str, signature: str, secret: str) -> bool:
    """True only if `signature` is a valid, current-version signature over
    exactly this `(service, data)` pair under `secret`. Never raises --
    `signature`/`service`/`data` come straight off a Redis stream any
    network peer on the flat compose network can write to, so any
    malformed, wrong-type, or adversarially-crafted input must fail
    closed as False, matching audit/signing.py's own contract exactly.
    """
    try:
        if not signature or not isinstance(signature, str):
            return False
        if not service or not isinstance(service, str):
            return False
        if data is None:
            return False

        version, sep, mac_hex = signature.partition(":")
        if not sep or version != _SIGNING_VERSION:
            return False

        expected = hmac.new(
            _signing_key(secret), _signing_message(version, service, data), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(mac_hex, expected)
    except Exception:
        return False


def classify_event_integrity(
    service: Optional[str], signature: Optional[str], data: str, secret: str
) -> str:
    """Mirrors omnibioai-security-audit's consumers/processor.py::
    classify_event_integrity exactly: the missing-signature check happens
    before verify_audit_event() (order matters -- that function already
    collapses "missing" and "invalid" into the same False, correctly,
    since that distinction is this caller's business, not the signing
    module's). `data` must be the exact raw stream string (fields["data"]),
    never a re-serialization -- the MAC covers the exact transmitted
    bytes. Returns exactly one of "valid" / "invalid" / "unsigned" --
    never raises.
    """
    if not signature:
        return "unsigned"
    return "valid" if verify_audit_event(service, data, signature, secret) else "invalid"


_CONNECT_TIMEOUT_S = 5
_WINDOW_DAYS = 7
_MAX_ENTRIES = 200_000
_HEALTH_SAMPLE_CAP = 50

# auth_failed/policy_denied/hpc_denied fire *before* a response object exists,
# so the audit payload carries no status_code -- same inference
# checks/gateway_traffic.py already applies, from the gateway's middleware
# source (app/middleware/auth.py, policy.py, hpc.py), where each path always
# returns exactly this status.
_DENY_EVENT_STATUS = {
    "auth_failed": 401,
    "policy_denied": 403,
    "hpc_denied": 403,
}

_EMPTY: dict[str, Any] = {
    "window_days": _WINDOW_DAYS,
    "total_events": 0,
    "health_check_pings": 0,
    "distinct_actors": 0,
    "event_type_breakdown": [],
    "decision_breakdown": {"allow": 0, "deny": 0},
    "reason_breakdown": [],
    "status_code_breakdown": {},
    "events": [],
}


def _is_health_ping(event_type: str, action: str) -> bool:
    return event_type == "request" and action.endswith("/health")


def get_audit_trail() -> dict[str, Any]:
    try:
        import redis

        r = redis.Redis.from_url(
            AUDIT_REDIS, socket_connect_timeout=_CONNECT_TIMEOUT_S,
            socket_timeout=_CONNECT_TIMEOUT_S, decode_responses=True,
        )
        cutoff_ms = int(datetime.datetime.now().timestamp() * 1000) - _WINDOW_DAYS * 86400 * 1000
        entries = r.xrange("audit:events", min=str(cutoff_ms), count=_MAX_ENTRIES)
    except Exception:
        return dict(_EMPTY)

    total_events = 0
    health_pings = 0
    actors: set[str] = set()
    event_type_counts: dict[str, int] = {}
    decision_counts = {"allow": 0, "deny": 0}
    reason_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    non_health_events: list[dict[str, Any]] = []
    health_events: list[dict[str, Any]] = []

    for eid, fields in entries:
        raw_data = fields.get("data", "{}")
        try:
            event = json.loads(raw_data)
        except (TypeError, ValueError):
            continue

        event_type = event.get("event_type", "unknown")
        action = event.get("action", "") or ""
        decision = event.get("decision")
        reason = event.get("reason")
        user_id = event.get("user_id")
        status_code = event.get("status_code")
        if status_code is None:
            status_code = _DENY_EVENT_STATUS.get(event_type)

        total_events += 1
        event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1
        if decision in decision_counts:
            decision_counts[decision] += 1
        if reason:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if status_code is not None:
            key = str(status_code)
            status_counts[key] = status_counts.get(key, 0) + 1
        if user_id:
            actors.add(str(user_id))

        is_health = _is_health_ping(event_type, action)
        if is_health:
            health_pings += 1

        # HIPAA PR3c: additive only -- does not affect total_events, any
        # breakdown, or whether this event appears in `events` below.
        # unsigned/invalid events are still displayed, just labeled, so an
        # admin can see a forged/tampered event rather than have it
        # silently dropped or, worse, silently trusted.
        integrity_status = classify_event_integrity(
            event.get("service"), fields.get("sig"), raw_data, JWT_SECRET
        )

        ms = int(eid.split("-")[0])
        record = {
            "id": eid,
            "timestamp": datetime.datetime.fromtimestamp(
                ms / 1000, tz=datetime.timezone.utc
            ).isoformat(),
            "event_type": event_type,
            "user_id": user_id,
            "endpoint": event.get("endpoint"),
            "action": action,
            "decision": decision,
            "reason": reason,
            "status_code": status_code,
            "latency_ms": event.get("latency_ms"),
            "trace_id": event.get("trace_id"),
            "is_health_check": is_health,
            "integrity_status": integrity_status,
        }
        if is_health:
            health_events.append(record)
        else:
            non_health_events.append(record)

    # health_events is already in ascending (oldest-first) order from XRANGE,
    # so the tail is the most recent -- keep only a small sample, the rest
    # add no analytical value (near-identical rows), but the aggregate counts
    # above are computed over the true full window regardless.
    health_sample = health_events[-_HEALTH_SAMPLE_CAP:]
    events = sorted(non_health_events + health_sample, key=lambda e: e["id"], reverse=True)

    event_type_breakdown = [
        {"event_type": et, "count": c}
        for et, c in sorted(event_type_counts.items(), key=lambda kv: -kv[1])
    ]
    reason_breakdown = [
        {"reason": rs, "count": c}
        for rs, c in sorted(reason_counts.items(), key=lambda kv: -kv[1])
    ]

    return {
        "window_days": _WINDOW_DAYS,
        "total_events": total_events,
        "health_check_pings": health_pings,
        "distinct_actors": len(actors),
        "event_type_breakdown": event_type_breakdown,
        "decision_breakdown": decision_counts,
        "reason_breakdown": reason_breakdown,
        "status_code_breakdown": status_counts,
        "events": events,
    }
