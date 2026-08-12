"""The analytics worker: a Redis Streams consumer-group pipeline that
drains `interactions:events` and `audit:events` into the Redis aggregates
`aggregator.py` owns. Deliberately a separate process from `main.py`'s
FastAPI app (run via `python -m control_center.analytics.consumer`), not
a background task started on API startup -- mirrors
`omnibioai-auth/app/workers/interaction_consumer.py`'s own reasoning
exactly: ingestion must survive API restarts/deploys, the consumer
workload scales independently of API request volume, and API request
latency must never depend on a Redis Streams read happening on the
ingestion side.

One consumer group name (`analytics-workers`) created independently on
both streams, read in a single blocking XREADGROUP call across both
stream keys -- Redis supports this natively (a consumer group is
per-stream, but nothing stops the same group *name* existing on several
streams, or one XREADGROUP call requesting `>` from several of them at
once). This is what lets one process/container read both streams instead
of needing two, without inventing anything Redis Streams doesn't already
support.

Consumer identity is STABLE (ANALYTICS_CONSUMER_NAME, a fixed default),
exactly like interaction_consumer.py's own point 1: a restarted worker
can reclaim its own crash-orphaned pending entries via
`read_own_pending`/`_drain_own_pending`, which a per-PID identity could
never do. No XCLAIM/XAUTOCLAIM anywhere (single-replica deployment, same
as that precedent).

A malformed payload (bad JSON, missing a required field) is logged and
left UNACKED, not dead-lettered -- the same, only established convention
for this exact situation in this codebase (interaction_consumer.py's own
handle_message docstring explains why: no dead-letter/quarantine
mechanism exists anywhere here, and inventing one unilaterally for this
PR would be a new, undiscussed production policy).
"""
from __future__ import annotations

import json
import logging
import os
import signal
from typing import Optional

from redis import Redis
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

from control_center.analytics import aggregator
from control_center.analytics.metrics import EVENTS_FAILED
from control_center.analytics.schemas import normalize_interaction_event

logger = logging.getLogger("omnibioai.control_center.analytics.consumer")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
CONSUMER_GROUP = os.getenv("ANALYTICS_CONSUMER_GROUP", "analytics-workers")
CONSUMER_NAME = os.getenv("ANALYTICS_CONSUMER_NAME", "analytics-worker")
READ_COUNT = int(os.getenv("ANALYTICS_READ_COUNT", "10"))
READ_BLOCK_MS = int(os.getenv("ANALYTICS_READ_BLOCK_MS", "5000"))

INTERACTIONS_STREAM = "interactions:events"
AUDIT_STREAM = "audit:events"
STREAMS = (INTERACTIONS_STREAM, AUDIT_STREAM)

# checks/gateway_traffic.py's own parsing of this exact stream (the one
# proven-working reader of audit:events in this codebase) treats
# event_type == "request" as a completed request and a handful of
# specific event_types as pre-response denials, each with a known,
# hardcoded status -- reused verbatim rather than re-derived, so this
# consumer never drifts from that existing, already-shipped parser.
_DENY_EVENT_TYPES = {"auth_failed", "policy_denied", "hpc_denied"}


class AnalyticsStreamConsumer:
    """Thin wrapper over the redis-py Streams API this worker needs --
    same ensure_group/read_own_pending/read_new/ack shape as
    interaction_consumer.py::InteractionStreamReader, extended to operate
    across multiple stream keys under one consumer group.
    """

    def __init__(self):
        self.redis = Redis.from_url(REDIS_URL, decode_responses=True)

    def ensure_groups(self, group: Optional[str] = None) -> None:
        group = group or CONSUMER_GROUP
        for stream in STREAMS:
            try:
                self.redis.xgroup_create(stream, group, id="0-0", mkstream=True)
            except ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    raise

    def read_own_pending(self, stream: str, consumer: Optional[str] = None, group: Optional[str] = None, count: int = 100, start: str = "0"):
        consumer = consumer or CONSUMER_NAME
        group = group or CONSUMER_GROUP
        result = self.redis.xreadgroup(group, consumer, {stream: start}, count=count)
        return result or []

    def read_new(self, consumer: Optional[str] = None, group: Optional[str] = None, count: Optional[int] = None, block: Optional[int] = None):
        consumer = consumer or CONSUMER_NAME
        group = group or CONSUMER_GROUP
        count = count if count is not None else READ_COUNT
        block = block if block is not None else READ_BLOCK_MS
        result = self.redis.xreadgroup(group, consumer, {s: ">" for s in STREAMS}, count=count, block=block)
        return result or []

    def ack(self, stream: str, message_id: str, group: Optional[str] = None) -> None:
        group = group or CONSUMER_GROUP
        self.redis.xack(stream, group, message_id)

    def pending_count(self, stream: str, group: Optional[str] = None) -> int:
        group = group or CONSUMER_GROUP
        try:
            summary = self.redis.xpending(stream, group)
            return int(summary.get("pending", 0)) if isinstance(summary, dict) else 0
        except Exception:
            return 0


def _handle_interaction_message(fields: dict) -> bool:
    """Parses+applies one interactions:events message. Returns True if
    it was successfully applied (including "already processed, safe
    no-op" -- see aggregator.apply_interaction_event), False if the
    payload was malformed and should be left unacked."""
    try:
        payload = json.loads(fields["data"])
    except (KeyError, json.JSONDecodeError) as e:
        logger.warning("analytics_consumer_parse_failed stream=%s error=%s", INTERACTIONS_STREAM, e)
        return False

    try:
        event = normalize_interaction_event(payload)
    except (KeyError, ValueError) as e:
        logger.warning("analytics_consumer_normalize_failed stream=%s error=%s", INTERACTIONS_STREAM, e)
        return False

    aggregator.apply_interaction_event(event)
    return True


def _handle_audit_message(fields: dict) -> bool:
    """Parses+applies one audit:events message. Mirrors
    checks/gateway_traffic.py's own field extraction for this stream
    exactly (event_type/action/decision/latency_ms/status_code), since
    that is the one proven-working parser for this wire shape already in
    this codebase."""
    try:
        event = json.loads(fields["data"])
    except (KeyError, json.JSONDecodeError) as e:
        logger.warning("analytics_consumer_parse_failed stream=%s error=%s", AUDIT_STREAM, e)
        return False

    event_id = event.get("event_id")
    timestamp_raw = event.get("timestamp")
    if not event_id or not timestamp_raw:
        logger.warning("analytics_consumer_missing_required_field stream=%s", AUDIT_STREAM)
        return False

    from datetime import datetime
    try:
        timestamp = datetime.fromisoformat(timestamp_raw.replace("Z", "+00:00"))
    except (TypeError, ValueError) as e:
        logger.warning("analytics_consumer_bad_timestamp stream=%s error=%s", AUDIT_STREAM, e)
        return False

    event_type = event.get("event_type")
    action = event.get("action") or ""
    is_health = action.endswith("/health")
    is_request = (event_type == "request" and not is_health) or event_type in _DENY_EVENT_TYPES
    is_error = event.get("decision") == "deny" or event_type in _DENY_EVENT_TYPES
    latency_ms = event.get("latency_ms")
    if not isinstance(latency_ms, (int, float)):
        latency_ms = None

    aggregator.apply_audit_event(
        event_id=event_id,
        timestamp=timestamp,
        is_request=is_request,
        is_error=is_error,
        latency_ms=latency_ms,
    )
    return True


_HANDLERS = {
    INTERACTIONS_STREAM: _handle_interaction_message,
    AUDIT_STREAM: _handle_audit_message,
}


def handle_message(consumer: AnalyticsStreamConsumer, stream: str, message_id: str, fields: dict) -> bool:
    """READ -> VALIDATE -> APPLY -> ACK, in that order, only acking on
    success. A malformed payload is logged and left pending (redelivered
    on the next own-pending drain), never dropped, never crash-loops the
    worker -- see this module's own docstring."""
    handler = _HANDLERS.get(stream)
    if handler is None:  # pragma: no cover -- defensive; STREAMS is the only source of stream names
        return False

    try:
        ok = handler(fields)
    except Exception:
        logger.exception("analytics_consumer_handler_failed stream=%s message_id=%s", stream, message_id)
        EVENTS_FAILED.labels(stream=stream).inc()
        return False

    if not ok:
        EVENTS_FAILED.labels(stream=stream).inc()
        return False

    consumer.ack(stream, message_id)
    return True


def _drain_own_pending(consumer: AnalyticsStreamConsumer) -> None:
    """Startup crash-recovery pass, once per stream: pages forward
    through this consumer's own pending entries, reprocessing each
    exactly like a live message. Safe to reprocess -- both
    aggregator.apply_* functions are idempotent on event id (see their
    own docstrings)."""
    for stream in STREAMS:
        start = "0"
        while True:
            response = consumer.read_own_pending(stream, start=start)
            messages = [
                (message_id, fields)
                for _stream_name, msgs in response
                for message_id, fields in msgs
            ]
            if not messages:
                break
            for message_id, fields in messages:
                handle_message(consumer, stream, message_id, fields)
            start = messages[-1][0]


_shutdown_requested = False


def _request_shutdown(signum, frame):  # pragma: no cover - exercised via run()'s flag directly
    global _shutdown_requested
    _shutdown_requested = True


def run(max_iterations: Optional[int] = None) -> None:
    """Main consumer loop. `max_iterations` bounds the loop for tests;
    the __main__ entrypoint below leaves it None to run until
    SIGTERM/SIGINT. Same graceful-shutdown shape as
    interaction_consumer.py::run: a signal sets a flag checked at the
    top of each iteration, safe regardless of exactly when it fires
    since a message is only ever acked after its aggregate write
    already succeeded.
    """
    global _shutdown_requested
    _shutdown_requested = False

    consumer = AnalyticsStreamConsumer()
    consumer.ensure_groups()
    _drain_own_pending(consumer)

    iterations = 0
    while not _shutdown_requested and (max_iterations is None or iterations < max_iterations):
        try:
            response = consumer.read_new()
        except RedisTimeoutError:
            # Expected on an idle stream -- see interaction_consumer.py's
            # identical handling for why this isn't a failure.
            response = []
        except Exception as e:
            logger.warning("analytics_consumer_read_failed error=%s", e)
            response = []

        for stream_name, messages in response:
            for message_id, fields in messages:
                handle_message(consumer, stream_name, message_id, fields)
        iterations += 1


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)
    logger.info(
        "analytics_consumer_starting group=%s consumer=%s streams=%s",
        CONSUMER_GROUP, CONSUMER_NAME, STREAMS,
    )
    run()
