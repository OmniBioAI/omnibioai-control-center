"""
tests/test_analytics_tes_client.py

Unit tests for control_center.analytics.tes_client.
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from control_center.analytics import tes_client


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


class GetRunsTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_success_returns_list(self) -> None:
        runs = [{"id": "1", "state": "COMPLETED"}]
        with patch("control_center.analytics.tes_client.httpx.AsyncClient", return_value=_mock_client(_resp(200, runs))):
            result = await tes_client.get_runs("Bearer tok")
        self.assertEqual(result, runs)

    async def test_non_list_body_returns_none(self) -> None:
        with patch("control_center.analytics.tes_client.httpx.AsyncClient", return_value=_mock_client(_resp(200, {"not": "a list"}))):
            result = await tes_client.get_runs("Bearer tok")
        self.assertIsNone(result)

    async def test_non_2xx_returns_none(self) -> None:
        with patch("control_center.analytics.tes_client.httpx.AsyncClient", return_value=_mock_client(_resp(500))):
            result = await tes_client.get_runs("Bearer tok")
        self.assertIsNone(result)

    async def test_unreachable_returns_none(self) -> None:
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        with patch("control_center.analytics.tes_client.httpx.AsyncClient", return_value=mock_ctx):
            result = await tes_client.get_runs("Bearer tok")
        self.assertIsNone(result)

    async def test_no_authorization_sends_no_header(self) -> None:
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
