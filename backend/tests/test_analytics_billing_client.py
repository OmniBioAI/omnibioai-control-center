"""
tests/test_analytics_billing_client.py

Unit tests for control_center.analytics.billing_client: get_usage()
distinguishes "billing service unreachable" (available=False) from
"billing service reachable but has no data for this org / gave us an
unparseable body" (available=True, body=None) so callers can render the
right degraded-state message; get_subscription()/get_usage_limits() hit
their expected billing-service paths.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from control_center.analytics import billing_client


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


class GetUsageTestCase(unittest.IsolatedAsyncioTestCase):
    """get_usage()'s (available, body) contract distinguishing a reachable
    billing service (even with no/unparseable data) from an unreachable one."""

    async def test_success_returns_available_and_body(self) -> None:
        """A 200 response returns (True, <parsed body>)."""
        with patch("control_center.analytics.billing_client.httpx.AsyncClient", return_value=_mock_client(_resp(200, {"services": []}))):
            available, body = await billing_client.get_usage(1, "Bearer tok")
        self.assertTrue(available)
        self.assertEqual(body, {"services": []})

    async def test_404_is_available_but_no_body(self) -> None:
        """A 404 (billing service reachable, no data for this org) is
        available=True with body=None, not available=False."""
        with patch("control_center.analytics.billing_client.httpx.AsyncClient", return_value=_mock_client(_resp(404))):
            available, body = await billing_client.get_usage(1, "Bearer tok")
        self.assertTrue(available)
        self.assertIsNone(body)

    async def test_unreachable_is_not_available(self) -> None:
        """A connection failure to the billing service returns (False, None)."""
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
        """A 200 response with an unparseable body is still available=True
        (the service was reachable), just with body=None."""
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("bad json")
        with patch("control_center.analytics.billing_client.httpx.AsyncClient", return_value=_mock_client(resp)):
            available, body = await billing_client.get_usage(1, "Bearer tok")
        self.assertTrue(available)
        self.assertIsNone(body)

    async def test_no_authorization_sends_no_header(self) -> None:
        """Calling get_usage(..., None) sends an empty headers dict -- no
        Authorization key at all."""
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
    """get_subscription()/get_usage_limits() hit their expected
    billing-service URL paths for a given organization id."""

    async def test_get_subscription_hits_expected_path(self) -> None:
        """get_subscription() requests
        /billing/organizations/{org_id}/subscription and returns the body."""
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
        """get_usage_limits() requests
        /billing/organizations/{org_id}/subscription/usage-limits."""
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
