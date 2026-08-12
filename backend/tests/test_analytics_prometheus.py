"""
tests/test_analytics_prometheus.py

Unit tests for control_center.analytics.prometheus. Since no Prometheus
server is deployed anywhere in this workspace (see the module's own
docstring), the "unavailable" path is the one that matters most in
practice -- covered first and most thoroughly here, alongside the
success path for when a real server does exist.
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from control_center.analytics import prometheus


def _resp(status_code: int, json_body=None) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_body
    return r


def _mock_client(response: MagicMock):
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=response)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


class IsConfiguredTestCase(unittest.TestCase):
    def test_empty_url_is_not_configured(self) -> None:
        with patch.object(prometheus, "PROMETHEUS_URL", ""):
            self.assertFalse(prometheus.is_configured())

    def test_nonempty_url_is_configured(self) -> None:
        with patch.object(prometheus, "PROMETHEUS_URL", "http://prometheus:9090"):
            self.assertTrue(prometheus.is_configured())


class InstantQueryTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_not_configured_returns_unavailable(self) -> None:
        with patch.object(prometheus, "PROMETHEUS_URL", ""):
            result = await prometheus.instant_query("up")
        self.assertEqual(result, {"available": False, "result": None})

    async def test_unreachable_returns_unavailable(self) -> None:
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
        with (
            patch.object(prometheus, "PROMETHEUS_URL", "http://prometheus:9090"),
            patch("control_center.analytics.prometheus.httpx.AsyncClient", return_value=_mock_client(_resp(500))),
        ):
            result = await prometheus.instant_query("up")
        self.assertEqual(result, {"available": False, "result": None})

    async def test_status_not_success_returns_unavailable(self) -> None:
        body = {"status": "error", "error": "bad query"}
        with (
            patch.object(prometheus, "PROMETHEUS_URL", "http://prometheus:9090"),
            patch("control_center.analytics.prometheus.httpx.AsyncClient", return_value=_mock_client(_resp(200, body))),
        ):
            result = await prometheus.instant_query("up")
        self.assertEqual(result, {"available": False, "result": None})

    async def test_success_returns_result_vector(self) -> None:
        body = {"status": "success", "data": {"resultType": "vector", "result": [{"metric": {}, "value": [1, "1"]}]}}
        with (
            patch.object(prometheus, "PROMETHEUS_URL", "http://prometheus:9090"),
            patch("control_center.analytics.prometheus.httpx.AsyncClient", return_value=_mock_client(_resp(200, body))),
        ):
            result = await prometheus.instant_query("up")
        self.assertTrue(result["available"])
        self.assertEqual(result["result"], [{"metric": {}, "value": [1, "1"]}])

    async def test_malformed_json_returns_unavailable(self) -> None:
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
        body = {"status": "success", "data": {}}
        with (
            patch.object(prometheus, "PROMETHEUS_URL", "http://prometheus:9090"),
            patch("control_center.analytics.prometheus.httpx.AsyncClient", return_value=_mock_client(_resp(200, body))),
        ):
            result = await prometheus.instant_query("up")
        self.assertEqual(result, {"available": False, "result": None})


class RangeQueryTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_success_returns_result(self) -> None:
        body = {"status": "success", "data": {"resultType": "matrix", "result": [{"values": [[1, "2"]]}]}}
        with (
            patch.object(prometheus, "PROMETHEUS_URL", "http://prometheus:9090"),
            patch("control_center.analytics.prometheus.httpx.AsyncClient", return_value=_mock_client(_resp(200, body))),
        ):
            result = await prometheus.range_query("up", start=0, end=100)
        self.assertTrue(result["available"])

    async def test_not_configured_returns_unavailable(self) -> None:
        with patch.object(prometheus, "PROMETHEUS_URL", ""):
            result = await prometheus.range_query("up", start=0, end=100)
        self.assertEqual(result, {"available": False, "result": None})

    async def test_success_status_but_missing_result_key_returns_unavailable(self) -> None:
        body = {"status": "success", "data": {}}
        with (
            patch.object(prometheus, "PROMETHEUS_URL", "http://prometheus:9090"),
            patch("control_center.analytics.prometheus.httpx.AsyncClient", return_value=_mock_client(_resp(200, body))),
        ):
            result = await prometheus.range_query("up", start=0, end=100)
        self.assertEqual(result, {"available": False, "result": None})


class ExtractScalarTestCase(unittest.TestCase):
    def test_empty_result_returns_none(self) -> None:
        self.assertIsNone(prometheus._extract_scalar([]))

    def test_extracts_float_value(self) -> None:
        result = [{"value": [1700000000, "0.123"]}]
        self.assertEqual(prometheus._extract_scalar(result), 0.123)

    def test_malformed_shape_returns_none(self) -> None:
        self.assertIsNone(prometheus._extract_scalar([{"unexpected": True}]))

    def test_nan_value_returns_none(self) -> None:
        result = [{"value": [1700000000, "NaN"]}]
        self.assertIsNone(prometheus._extract_scalar(result))


class QueryLatencyQuantilesTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_not_configured_returns_unavailable(self) -> None:
        with patch.object(prometheus, "PROMETHEUS_URL", ""):
            result = await prometheus.query_latency_quantiles()
        self.assertEqual(result, {"available": False, "result": None})

    async def test_all_three_quantiles_returned_on_success(self) -> None:
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
