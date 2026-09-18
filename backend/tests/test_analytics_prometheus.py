"""
tests/test_analytics_prometheus.py

Unit tests for control_center.analytics.prometheus. Since no Prometheus
server is deployed anywhere in this workspace (see the module's own
docstring), the "unavailable" path is the one that matters most in
practice -- covered first and most thoroughly here, alongside the
success path for when a real server does exist.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from control_center.analytics import prometheus


def _resp(status_code: int, json_body=None) -> MagicMock:
    """A MagicMock httpx.Response stand-in with a fixed status/JSON body."""
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_body
    return r


def _mock_client(response: MagicMock):
    """An async-context-manager mock of httpx.AsyncClient whose .get()
    always returns `response`."""
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=response)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


class IsConfiguredTestCase(unittest.TestCase):
    """is_configured()'s check of whether PROMETHEUS_URL is set."""

    def test_empty_url_is_not_configured(self) -> None:
        """An empty PROMETHEUS_URL is not configured."""
        with patch.object(prometheus, "PROMETHEUS_URL", ""):
            self.assertFalse(prometheus.is_configured())

    def test_nonempty_url_is_configured(self) -> None:
        """A non-empty PROMETHEUS_URL is configured."""
        with patch.object(prometheus, "PROMETHEUS_URL", "http://prometheus:9090"):
            self.assertTrue(prometheus.is_configured())


class InstantQueryTestCase(unittest.IsolatedAsyncioTestCase):
    """instant_query()'s {"available", "result"} contract across every
    failure mode (not configured, unreachable, non-2xx, query error,
    malformed JSON, missing result key) and the success path."""

    async def test_not_configured_returns_unavailable(self) -> None:
        """No PROMETHEUS_URL set returns available=False without
        attempting a request."""
        with patch.object(prometheus, "PROMETHEUS_URL", ""):
            result = await prometheus.instant_query("up")
        self.assertEqual(result, {"available": False, "result": None})

    async def test_unreachable_returns_unavailable(self) -> None:
        """A connection failure returns available=False."""
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.object(prometheus, "PROMETHEUS_URL", "http://prometheus:9090"),
            patch("control_center.analytics.prometheus.httpx.AsyncClient", return_value=mock_ctx),
        ):
            result = await prometheus.instant_query("up")
        self.assertEqual(result, {"available": False, "result": None})

    async def test_non_2xx_returns_unavailable(self) -> None:
        """A non-2xx HTTP status returns available=False."""
        with (
            patch.object(prometheus, "PROMETHEUS_URL", "http://prometheus:9090"),
            patch("control_center.analytics.prometheus.httpx.AsyncClient", return_value=_mock_client(_resp(500))),
        ):
            result = await prometheus.instant_query("up")
        self.assertEqual(result, {"available": False, "result": None})

    async def test_status_not_success_returns_unavailable(self) -> None:
        """A 200 response whose body's own "status" field is "error"
        (a Prometheus query error, not an HTTP error) returns
        available=False."""
        body = {"status": "error", "error": "bad query"}
        with (
            patch.object(prometheus, "PROMETHEUS_URL", "http://prometheus:9090"),
            patch("control_center.analytics.prometheus.httpx.AsyncClient", return_value=_mock_client(_resp(200, body))),
        ):
            result = await prometheus.instant_query("up")
        self.assertEqual(result, {"available": False, "result": None})

    async def test_success_returns_result_vector(self) -> None:
        """A successful query returns available=True with the parsed
        result vector."""
        body = {"status": "success", "data": {"resultType": "vector", "result": [{"metric": {}, "value": [1, "1"]}]}}
        with (
            patch.object(prometheus, "PROMETHEUS_URL", "http://prometheus:9090"),
            patch("control_center.analytics.prometheus.httpx.AsyncClient", return_value=_mock_client(_resp(200, body))),
        ):
            result = await prometheus.instant_query("up")
        self.assertTrue(result["available"])
        self.assertEqual(result["result"], [{"metric": {}, "value": [1, "1"]}])

    async def test_malformed_json_returns_unavailable(self) -> None:
        """A response body that fails to parse as JSON returns
        available=False rather than raising."""
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("bad json")
        with (
            patch.object(prometheus, "PROMETHEUS_URL", "http://prometheus:9090"),
            patch("control_center.analytics.prometheus.httpx.AsyncClient", return_value=_mock_client(resp)),
        ):
            result = await prometheus.instant_query("up")
        self.assertEqual(result, {"available": False, "result": None})


    async def test_success_status_but_missing_result_key_returns_unavailable(self) -> None:
        """A "status": "success" body whose data dict is missing the
        "result" key entirely returns available=False rather than
        raising a KeyError."""
        body = {"status": "success", "data": {}}
        with (
            patch.object(prometheus, "PROMETHEUS_URL", "http://prometheus:9090"),
            patch("control_center.analytics.prometheus.httpx.AsyncClient", return_value=_mock_client(_resp(200, body))),
        ):
            result = await prometheus.instant_query("up")
        self.assertEqual(result, {"available": False, "result": None})


class RangeQueryTestCase(unittest.IsolatedAsyncioTestCase):
    """range_query()'s success/failure contract, mirroring
    InstantQueryTestCase's key cases for the range-query endpoint."""

    async def test_success_returns_result(self) -> None:
        """A successful range query returns available=True."""
        body = {"status": "success", "data": {"resultType": "matrix", "result": [{"values": [[1, "2"]]}]}}
        with (
            patch.object(prometheus, "PROMETHEUS_URL", "http://prometheus:9090"),
            patch("control_center.analytics.prometheus.httpx.AsyncClient", return_value=_mock_client(_resp(200, body))),
        ):
            result = await prometheus.range_query("up", start=0, end=100)
        self.assertTrue(result["available"])

    async def test_not_configured_returns_unavailable(self) -> None:
        """No PROMETHEUS_URL set returns available=False."""
        with patch.object(prometheus, "PROMETHEUS_URL", ""):
            result = await prometheus.range_query("up", start=0, end=100)
        self.assertEqual(result, {"available": False, "result": None})

    async def test_success_status_but_missing_result_key_returns_unavailable(self) -> None:
        """A "status": "success" body missing the "result" key returns
        available=False rather than raising."""
        body = {"status": "success", "data": {}}
        with (
            patch.object(prometheus, "PROMETHEUS_URL", "http://prometheus:9090"),
            patch("control_center.analytics.prometheus.httpx.AsyncClient", return_value=_mock_client(_resp(200, body))),
        ):
            result = await prometheus.range_query("up", start=0, end=100)
        self.assertEqual(result, {"available": False, "result": None})


class ExtractScalarTestCase(unittest.TestCase):
    """_extract_scalar()'s parsing of a Prometheus instant-vector result
    into a single float, failing safe to None on any malformed shape."""

    def test_empty_result_returns_none(self) -> None:
        """An empty result list returns None."""
        self.assertIsNone(prometheus._extract_scalar([]))

    def test_extracts_float_value(self) -> None:
        """A well-formed [timestamp, "value"] pair parses to the float."""
        result = [{"value": [1700000000, "0.123"]}]
        self.assertEqual(prometheus._extract_scalar(result), 0.123)

    def test_malformed_shape_returns_none(self) -> None:
        """A result entry missing the "value" key returns None."""
        self.assertIsNone(prometheus._extract_scalar([{"unexpected": True}]))

    def test_nan_value_returns_none(self) -> None:
        """A literal "NaN" value string returns None rather than a NaN float."""
        result = [{"value": [1700000000, "NaN"]}]
        self.assertIsNone(prometheus._extract_scalar(result))


class QueryLatencyQuantilesTestCase(unittest.IsolatedAsyncioTestCase):
    """query_latency_quantiles()'s combination of three separate
    instant_query() calls (p50/p95/p99) into one result, failing closed
    if any one of them is unavailable."""

    async def test_not_configured_returns_unavailable(self) -> None:
        """No PROMETHEUS_URL set returns available=False."""
        with patch.object(prometheus, "PROMETHEUS_URL", ""):
            result = await prometheus.query_latency_quantiles()
        self.assertEqual(result, {"available": False, "result": None})

    async def test_all_three_quantiles_returned_on_success(self) -> None:
        """When all three quantile queries succeed, the result carries
        p50/p95/p99 with the correct values."""
        async def _fake_instant_query(promql: str):
            value = "0.05" if "0.5" in promql else "0.2" if "0.95" in promql else "0.5"
            return {"available": True, "result": [{"value": [1, value]}]}

        with (
            patch.object(prometheus, "PROMETHEUS_URL", "http://prometheus:9090"),
            patch.object(prometheus, "instant_query", side_effect=_fake_instant_query),
        ):
            result = await prometheus.query_latency_quantiles(job="control-center")
        self.assertTrue(result["available"])
        self.assertEqual(result["p50"], 0.05)
        self.assertEqual(result["p95"], 0.2)
        self.assertEqual(result["p99"], 0.5)

    async def test_any_quantile_unavailable_makes_whole_result_unavailable(self) -> None:
        """If even one of the three quantile queries (p99 here) is
        unavailable, the whole combined result is available=False."""
        async def _fake_instant_query(promql: str):
            if "0.99" in promql:
                return {"available": False, "result": None}
            return {"available": True, "result": [{"value": [1, "0.1"]}]}

        with (
            patch.object(prometheus, "PROMETHEUS_URL", "http://prometheus:9090"),
            patch.object(prometheus, "instant_query", side_effect=_fake_instant_query),
        ):
            result = await prometheus.query_latency_quantiles()
        self.assertEqual(result, {"available": False, "result": None})

    async def test_no_job_label_omits_selector(self) -> None:
        """job=None omits the job="..." PromQL selector entirely,
        rather than sending job="None"."""
        captured = {}

        async def _fake_instant_query(promql: str):
            captured["promql"] = promql
            return {"available": True, "result": [{"value": [1, "0.1"]}]}

        with (
            patch.object(prometheus, "PROMETHEUS_URL", "http://prometheus:9090"),
            patch.object(prometheus, "instant_query", side_effect=_fake_instant_query),
        ):
            await prometheus.query_latency_quantiles(job=None)
        self.assertNotIn('job="', captured["promql"])


if __name__ == "__main__":
    unittest.main()
