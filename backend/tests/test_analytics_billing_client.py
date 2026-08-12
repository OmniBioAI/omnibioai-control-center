"""
tests/test_analytics_billing_client.py

Unit tests for control_center.analytics.billing_client.
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from control_center.analytics import billing_client


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


class GetUsageTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_success_returns_available_and_body(self) -> None:
        with patch("control_center.analytics.billing_client.httpx.AsyncClient", return_value=_mock_client(_resp(200, {"services": []}))):
            available, body = await billing_client.get_usage(1, "Bearer tok")
        self.assertTrue(available)
        self.assertEqual(body, {"services": []})

    async def test_404_is_available_but_no_body(self) -> None:
        with patch("control_center.analytics.billing_client.httpx.AsyncClient", return_value=_mock_client(_resp(404))):
            available, body = await billing_client.get_usage(1, "Bearer tok")
        self.assertTrue(available)
        self.assertIsNone(body)

    async def test_unreachable_is_not_available(self) -> None:
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        with patch("control_center.analytics.billing_client.httpx.AsyncClient", return_value=mock_ctx):
            available, body = await billing_client.get_usage(1, "Bearer tok")
        self.assertFalse(available)
        self.assertIsNone(body)

    async def test_malformed_json_returns_available_with_none_body(self) -> None:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("bad json")
        with patch("control_center.analytics.billing_client.httpx.AsyncClient", return_value=_mock_client(resp)):
            available, body = await billing_client.get_usage(1, "Bearer tok")
        self.assertTrue(available)
        self.assertIsNone(body)

    async def test_no_authorization_sends_no_header(self) -> None:
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=_resp(200, {}))
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        with patch("control_center.analytics.billing_client.httpx.AsyncClient", return_value=mock_ctx):
            await billing_client.get_usage(1, None)
        _, kwargs = mock_client.get.call_args
        self.assertEqual(kwargs["headers"], {})


class GetSubscriptionAndUsageLimitsTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_get_subscription_hits_expected_path(self) -> None:
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=_resp(200, {"plan_name": "pro"}))
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        with patch("control_center.analytics.billing_client.httpx.AsyncClient", return_value=mock_ctx):
            available, body = await billing_client.get_subscription(7, "Bearer tok")
        self.assertTrue(available)
        self.assertEqual(body["plan_name"], "pro")
        called_url = mock_client.get.call_args[0][0]
        self.assertIn("/billing/organizations/7/subscription", called_url)

    async def test_get_usage_limits_hits_expected_path(self) -> None:
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=_resp(200, {"limit": 100}))
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        with patch("control_center.analytics.billing_client.httpx.AsyncClient", return_value=mock_ctx):
            available, body = await billing_client.get_usage_limits(7, "Bearer tok")
        self.assertTrue(available)
        called_url = mock_client.get.call_args[0][0]
        self.assertIn("/billing/organizations/7/subscription/usage-limits", called_url)


if __name__ == "__main__":
    unittest.main()
