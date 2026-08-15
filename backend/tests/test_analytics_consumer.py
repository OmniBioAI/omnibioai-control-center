"""
tests/test_analytics_consumer.py

Unit tests for control_center.analytics.consumer.

Covers the task brief's own consumer test list (Section 12): valid
event, malformed event, missing user ID, missing organization ID,
duplicate event, Redis failure, consumer restart, stream offset
persistence.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from unittest.mock import MagicMock, patch

from control_center.analytics import aggregator, consumer
from _fake_redis import FakeRedis


def _interaction_fields(**overrides) -> dict:
    payload = dict(
        interaction_id="int-1",
        timestamp="2026-01-15T10:30:00",
        organization_id=1,
        user_id=42,
        service="rag",
        interaction_type="query",
        action="rag.query",
        status="success",
        metadata={},
    )
    payload.update(overrides)
    return {"data": json.dumps(payload)}


def _audit_fields(*, sig: str | None = None, **overrides) -> dict:
    payload = dict(
        event_id="audit-1",
        timestamp="2026-01-15T10:30:00+00:00",
        service="api-gateway",
        event_type="request",
        action="/v1/query",
        decision="allow",
        latency_ms=120,
        status_code=200,
    )
    payload.update(overrides)
    fields: dict = {"data": json.dumps(payload)}
    if sig is not None:
        fields["sig"] = sig
    return fields


def _sign(service: str, data: str, secret: str) -> str:
    """Independent re-implementation of the sign side of the construction
    consumer.py's imported classify_event_integrity checks against -- see
    test_check_audit_trail.py's own identical helper."""
    mac = hmac.new(
        hashlib.sha256(f"omnibioai-audit-events:{secret}".encode()).digest(),
        f"v1\n{service}\n{data}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"v1:{mac}"


class HandleInteractionMessageTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeRedis()
        self._patcher = patch.object(aggregator, "_redis", self.fake)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_valid_event_applied(self) -> None:
        self.assertTrue(consumer._handle_interaction_message(_interaction_fields()))
        self.assertEqual(aggregator.read_agg("2026-01-15", org_id=1)["query_count"], 1)

    def test_malformed_json_returns_false(self) -> None:
        self.assertFalse(consumer._handle_interaction_message({"data": "not-json"}))

    def test_missing_data_field_returns_false(self) -> None:
        self.assertFalse(consumer._handle_interaction_message({}))

    def test_missing_organization_id_returns_false(self) -> None:
        payload = json.loads(_interaction_fields()["data"])
        del payload["organization_id"]
        self.assertFalse(consumer._handle_interaction_message({"data": json.dumps(payload)}))

    def test_missing_user_id_still_applies_but_no_active_user(self) -> None:
        payload = json.loads(_interaction_fields()["data"])
        del payload["user_id"]
        self.assertTrue(consumer._handle_interaction_message({"data": json.dumps(payload)}))
        self.assertEqual(aggregator.read_active_user_count(["2026-01-15"], org_id=1), 0)
        self.assertEqual(aggregator.read_agg("2026-01-15", org_id=1)["query_count"], 1)

    def test_duplicate_event_still_returns_true(self) -> None:
        consumer._handle_interaction_message(_interaction_fields())
        # A duplicate is a safe no-op from the handler's point of view --
        # aggregator.apply_interaction_event returning False just means
        # "already applied", not "failed to parse/validate". The message
        # should still be acked (see handle_message's own contract).
        self.assertTrue(consumer._handle_interaction_message(_interaction_fields()))
        self.assertEqual(aggregator.read_agg("2026-01-15", org_id=1)["query_count"], 1)


class HandleAuditMessageTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeRedis()
        self._patcher = patch.object(aggregator, "_redis", self.fake)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_valid_request_event_applied(self) -> None:
        self.assertTrue(consumer._handle_audit_message(_audit_fields()))
        self.assertEqual(aggregator.read_agg("2026-01-15")["request_count"], 1)

    def test_malformed_json_returns_false(self) -> None:
        self.assertFalse(consumer._handle_audit_message({"data": "not-json"}))

    def test_missing_event_id_returns_false(self) -> None:
        payload = json.loads(_audit_fields()["data"])
        del payload["event_id"]
        self.assertFalse(consumer._handle_audit_message({"data": json.dumps(payload)}))

    def test_bad_timestamp_returns_false(self) -> None:
        self.assertFalse(consumer._handle_audit_message(_audit_fields(timestamp="not-a-date")))

    def test_health_check_action_not_counted_as_request(self) -> None:
        self.assertTrue(consumer._handle_audit_message(_audit_fields(action="/svc/health")))
        self.assertEqual(aggregator.read_agg("2026-01-15")["request_count"], 0)

    def test_deny_event_type_counted_as_request_and_error(self) -> None:
        self.assertTrue(consumer._handle_audit_message(_audit_fields(event_type="auth_failed", decision=None)))
        agg = aggregator.read_agg("2026-01-15")
        self.assertEqual(agg["request_count"], 1)
        self.assertEqual(agg["request_error_count"], 1)

    def test_non_numeric_latency_treated_as_none(self) -> None:
        self.assertTrue(consumer._handle_audit_message(_audit_fields(latency_ms="not-a-number")))
        self.assertEqual(aggregator.read_agg("2026-01-15")["latency_count"], 0)

    # -- HIPAA PR3d: integrity-aware ingestion -----------------------------

    def test_unsigned_event_still_applied(self) -> None:
        """Backward compatibility, stated explicitly: unsigned is the
        pre-PR3b norm for this entire stream's history, not evidence of
        tampering. Every other test in this class already proves this
        implicitly (none of them sign), but this one says so directly."""
        self.assertTrue(consumer._handle_audit_message(_audit_fields()))
        self.assertEqual(aggregator.read_agg("2026-01-15")["request_count"], 1)

    def test_valid_signed_event_applied(self) -> None:
        base = _audit_fields()
        sig = _sign("api-gateway", base["data"], consumer.JWT_SECRET)
        self.assertTrue(consumer._handle_audit_message({"data": base["data"], "sig": sig}))
        self.assertEqual(aggregator.read_agg("2026-01-15")["request_count"], 1)

    def test_tampered_event_not_applied_but_acked(self) -> None:
        """Signed correctly, then published with a different payload under
        that same signature -- the exact mutation-must-be-caught scenario.
        Returns True (ACKed): a bad signature is permanent, not a
        transient failure, so leaving it pending would only accumulate a
        poison-pill entry -- distinct from test_malformed_json_returns_false
        above, which IS left pending since a parse failure could in
        principle be transient/fixable."""
        base = _audit_fields()
        sig = _sign("api-gateway", base["data"], consumer.JWT_SECRET)
        tampered_payload = json.loads(base["data"])
        tampered_payload["decision"] = "deny"
        tampered_fields = {"data": json.dumps(tampered_payload), "sig": sig}

        self.assertTrue(consumer._handle_audit_message(tampered_fields))
        agg = aggregator.read_agg("2026-01-15")
        self.assertEqual(agg["request_count"], 0)
        self.assertEqual(agg["request_error_count"], 0)

    def test_malformed_signature_not_applied_but_acked(self) -> None:
        ok = consumer._handle_audit_message(_audit_fields(sig="not-a-real-signature"))
        self.assertTrue(ok)  # must not raise, must still ack
        self.assertEqual(aggregator.read_agg("2026-01-15")["request_count"], 0)

    def test_wrong_secret_signature_never_silently_applied(self) -> None:
        base = _audit_fields()
        sig = _sign("api-gateway", base["data"], "a-different-secret-than-jwt_secret")
        ok = consumer._handle_audit_message({"data": base["data"], "sig": sig})
        self.assertTrue(ok)
        self.assertEqual(aggregator.read_agg("2026-01-15")["request_count"], 0)


class HandleMessageDispatchTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeRedis()
        self._patcher = patch.object(aggregator, "_redis", self.fake)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_acks_on_success(self) -> None:
        mock_consumer = MagicMock()
        ok = consumer.handle_message(mock_consumer, consumer.INTERACTIONS_STREAM, "1-0", _interaction_fields())
        self.assertTrue(ok)
        mock_consumer.ack.assert_called_once_with(consumer.INTERACTIONS_STREAM, "1-0")

    def test_does_not_ack_on_malformed_payload(self) -> None:
        mock_consumer = MagicMock()
        ok = consumer.handle_message(mock_consumer, consumer.INTERACTIONS_STREAM, "1-0", {"data": "not-json"})
        self.assertFalse(ok)
        mock_consumer.ack.assert_not_called()

    def test_handler_exception_does_not_crash_and_is_not_acked(self) -> None:
        mock_consumer = MagicMock()
        with patch.dict(consumer._HANDLERS, {consumer.INTERACTIONS_STREAM: MagicMock(side_effect=RuntimeError("boom"))}):
            ok = consumer.handle_message(mock_consumer, consumer.INTERACTIONS_STREAM, "1-0", _interaction_fields())
        self.assertFalse(ok)
        mock_consumer.ack.assert_not_called()

    def test_acks_invalid_signature_audit_message_without_applying_it(self) -> None:
        """HIPAA PR3d, at the dispatch level: an invalid-signature audit
        event IS acked (unlike test_does_not_ack_on_malformed_payload
        above) -- a bad signature is a permanent verdict, not a transient
        parse failure -- but never reaches the aggregator."""
        base = _audit_fields()
        sig = _sign("api-gateway", base["data"], "wrong-secret")
        mock_consumer = MagicMock()
        ok = consumer.handle_message(
            mock_consumer, consumer.AUDIT_STREAM, "1-0", {"data": base["data"], "sig": sig}
        )
        self.assertTrue(ok)
        mock_consumer.ack.assert_called_once_with(consumer.AUDIT_STREAM, "1-0")
        self.assertEqual(aggregator.read_agg("2026-01-15")["request_count"], 0)


class DrainOwnPendingTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeRedis()
        self._patcher = patch.object(aggregator, "_redis", self.fake)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_reprocesses_pending_entries_then_stops(self) -> None:
        """Simulates a crash-recovery pass: a previous run delivered one
        message per stream that was never acked. On restart, the drain
        must reprocess (idempotently) and stop once a page comes back
        empty -- this is the "consumer restart" / "stream offset
        persistence" behavior the task brief asks for, proven via the
        same own-pending-list mechanism omnibioai-auth's proven
        interaction_consumer.py already uses.
        """
        mock_consumer = MagicMock()
        mock_consumer.read_own_pending.side_effect = [
            [(consumer.INTERACTIONS_STREAM, [("1-0", _interaction_fields())])],
            [],
            [(consumer.AUDIT_STREAM, [("1-0", _audit_fields())])],
            [],
        ]
        consumer._drain_own_pending(mock_consumer)
        self.assertEqual(aggregator.read_agg("2026-01-15", org_id=1)["query_count"], 1)
        self.assertEqual(aggregator.read_agg("2026-01-15")["request_count"], 1)
        self.assertEqual(mock_consumer.read_own_pending.call_count, 4)

    def test_empty_first_page_does_not_reprocess(self) -> None:
        mock_consumer = MagicMock()
        mock_consumer.read_own_pending.return_value = []
        consumer._drain_own_pending(mock_consumer)
        self.assertEqual(mock_consumer.read_own_pending.call_count, len(consumer.STREAMS))


class AnalyticsStreamConsumerTestCase(unittest.TestCase):
    def test_ensure_groups_creates_group_on_both_streams(self) -> None:
        mock_redis = MagicMock()
        with patch("control_center.analytics.consumer.Redis.from_url", return_value=mock_redis):
            c = consumer.AnalyticsStreamConsumer()
            c.ensure_groups()
        self.assertEqual(mock_redis.xgroup_create.call_count, len(consumer.STREAMS))

    def test_ensure_groups_ignores_busygroup(self) -> None:
        from redis.exceptions import ResponseError
        mock_redis = MagicMock()
        mock_redis.xgroup_create.side_effect = ResponseError("BUSYGROUP Consumer Group name already exists")
        with patch("control_center.analytics.consumer.Redis.from_url", return_value=mock_redis):
            c = consumer.AnalyticsStreamConsumer()
            c.ensure_groups()  # must not raise

    def test_ensure_groups_reraises_other_response_errors(self) -> None:
        from redis.exceptions import ResponseError
        mock_redis = MagicMock()
        mock_redis.xgroup_create.side_effect = ResponseError("WRONGTYPE")
        with patch("control_center.analytics.consumer.Redis.from_url", return_value=mock_redis):
            c = consumer.AnalyticsStreamConsumer()
            with self.assertRaises(ResponseError):
                c.ensure_groups()

    def test_read_new_requests_all_streams(self) -> None:
        mock_redis = MagicMock()
        mock_redis.xreadgroup.return_value = None
        with patch("control_center.analytics.consumer.Redis.from_url", return_value=mock_redis):
            c = consumer.AnalyticsStreamConsumer()
            result = c.read_new()
        self.assertEqual(result, [])
        _, kwargs = mock_redis.xreadgroup.call_args
        streams_arg = mock_redis.xreadgroup.call_args[0][2]
        self.assertEqual(set(streams_arg.keys()), set(consumer.STREAMS))

    def test_pending_count_returns_zero_on_error(self) -> None:
        mock_redis = MagicMock()
        mock_redis.xpending.side_effect = RuntimeError("down")
        with patch("control_center.analytics.consumer.Redis.from_url", return_value=mock_redis):
            c = consumer.AnalyticsStreamConsumer()
            self.assertEqual(c.pending_count(consumer.INTERACTIONS_STREAM), 0)

    def test_pending_count_reads_summary(self) -> None:
        mock_redis = MagicMock()
        mock_redis.xpending.return_value = {"pending": 3}
        with patch("control_center.analytics.consumer.Redis.from_url", return_value=mock_redis):
            c = consumer.AnalyticsStreamConsumer()
            self.assertEqual(c.pending_count(consumer.INTERACTIONS_STREAM), 3)

    def test_read_own_pending_defaults_to_module_constants(self) -> None:
        mock_redis = MagicMock()
        mock_redis.xreadgroup.return_value = None
        with patch("control_center.analytics.consumer.Redis.from_url", return_value=mock_redis):
            c = consumer.AnalyticsStreamConsumer()
            result = c.read_own_pending(consumer.INTERACTIONS_STREAM)
        self.assertEqual(result, [])
        mock_redis.xreadgroup.assert_called_once_with(
            consumer.CONSUMER_GROUP, consumer.CONSUMER_NAME,
            {consumer.INTERACTIONS_STREAM: "0"}, count=100,
        )

    def test_ack_calls_xack(self) -> None:
        mock_redis = MagicMock()
        with patch("control_center.analytics.consumer.Redis.from_url", return_value=mock_redis):
            c = consumer.AnalyticsStreamConsumer()
            c.ack(consumer.INTERACTIONS_STREAM, "1-0")
        mock_redis.xack.assert_called_once_with(consumer.INTERACTIONS_STREAM, consumer.CONSUMER_GROUP, "1-0")


class RunLoopTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeRedis()
        self._patcher = patch.object(aggregator, "_redis", self.fake)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_run_processes_one_batch_and_stops_after_max_iterations(self) -> None:
        with patch.object(consumer, "AnalyticsStreamConsumer") as mock_cls:
            mock_instance = mock_cls.return_value
            mock_instance.read_own_pending.return_value = []
            mock_instance.read_new.return_value = [
                (consumer.INTERACTIONS_STREAM, [("1-0", _interaction_fields())]),
            ]
            consumer.run(max_iterations=1)
            mock_instance.ack.assert_called_once_with(consumer.INTERACTIONS_STREAM, "1-0")

    def test_run_swallows_redis_timeout(self) -> None:
        from redis.exceptions import TimeoutError as RedisTimeoutError
        with patch.object(consumer, "AnalyticsStreamConsumer") as mock_cls:
            mock_instance = mock_cls.return_value
            mock_instance.read_own_pending.return_value = []
            mock_instance.read_new.side_effect = RedisTimeoutError("idle")
            consumer.run(max_iterations=1)  # must not raise

    def test_run_swallows_generic_read_failure(self) -> None:
        with patch.object(consumer, "AnalyticsStreamConsumer") as mock_cls:
            mock_instance = mock_cls.return_value
            mock_instance.read_own_pending.return_value = []
            mock_instance.read_new.side_effect = RuntimeError("connection reset")
            consumer.run(max_iterations=1)  # must not raise

    def test_request_shutdown_sets_flag(self) -> None:
        consumer._shutdown_requested = False
        consumer._request_shutdown(None, None)
        self.assertTrue(consumer._shutdown_requested)
        consumer._shutdown_requested = False
