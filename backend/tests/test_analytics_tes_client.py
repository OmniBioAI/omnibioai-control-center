"""
tests/test_analytics_tes_client.py

Unit tests for control_center.analytics.tes_client.get_runs(): must
return the parsed list on a 2xx JSON-array response, and None (never
raise) on a non-list body, a non-2xx status, or an unreachable upstream;
must omit the Authorization header entirely rather than sending one with
a null/empty value when no token is supplied.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from control_center.analytics import tes_client


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


class GetRunsTestCase(unittest.IsolatedAsyncioTestCase):
    """get_runs()'s success/failure contract: a list on a good 2xx JSON
    array, None (never an exception) on anything else."""

    async def test_success_returns_list(self) -> None:
        """A 2xx response with a JSON array body returns that list as-is."""
        runs = [{"id": "1", "state": "COMPLETED"}]
        with patch("control_center.analytics.tes_client.httpx.AsyncClient", return_value=_mock_client(_resp(200, runs))):
            result = await tes_client.get_runs("Bearer tok")
        self.assertEqual(result, runs)

    async def test_non_list_body_returns_none(self) -> None:
        """A 2xx response whose JSON body is not a list returns None."""
        with patch("control_center.analytics.tes_client.httpx.AsyncClient", return_value=_mock_client(_resp(200, {"not": "a list"}))):
            result = await tes_client.get_runs("Bearer tok")
        self.assertIsNone(result)

    async def test_non_2xx_returns_none(self) -> None:
        """A non-2xx status code returns None rather than the body."""
        with patch("control_center.analytics.tes_client.httpx.AsyncClient", return_value=_mock_client(_resp(500))):
            result = await tes_client.get_runs("Bearer tok")
        self.assertIsNone(result)

    async def test_unreachable_returns_none(self) -> None:
        """A connection failure to the upstream TES service returns None
        rather than propagating the exception."""
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        with patch("control_center.analytics.tes_client.httpx.AsyncClient", return_value=mock_ctx):
            result = await tes_client.get_runs("Bearer tok")
        self.assertIsNone(result)

    async def test_no_authorization_sends_no_header(self) -> None:
        """Calling get_runs(None) sends an empty headers dict -- no
        Authorization key at all, not one set to None/""."""
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=_resp(200, []))
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        with patch("control_center.analytics.tes_client.httpx.AsyncClient", return_value=mock_ctx):
            await tes_client.get_runs(None)
        _, kwargs = mock_client.get.call_args
        self.assertEqual(kwargs["headers"], {})


if __name__ == "__main__":
    unittest.main()
