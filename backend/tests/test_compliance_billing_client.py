"""Unit tests for control_center.compliance.billing_client."""
from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from control_center.compliance import billing_client


def _resp(status_code: int, json_body=None) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_body
    return r


def _mock_client(*responses: MagicMock):
    mock_client = MagicMock()
    if len(responses) > 1:
        mock_client.get = AsyncMock(side_effect=list(responses))
    else:
        mock_client.get = AsyncMock(return_value=responses[0])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx, mock_client


class ListAllUsageEventsTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_single_page_stops_when_offset_reaches_total(self) -> None:
        ctx, mock_client = _mock_client(_resp(200, {"events": [{"event_id": "a"}], "total_count": 1}))
        with patch("control_center.compliance.billing_client.httpx.AsyncClient", return_value=ctx):
            events, truncated, unavailable = await billing_client.list_all_usage_events(
                organization_id=1, start_date=date(2026, 8, 1), end_date=date(2026, 8, 31), authorization="Bearer tok",
            )
        self.assertEqual(len(events), 1)
        self.assertFalse(truncated)
        self.assertFalse(unavailable)
        self.assertEqual(mock_client.get.call_count, 1)

    async def test_follows_pagination_via_offset(self) -> None:
        ctx, mock_client = _mock_client(
            _resp(200, {"events": [{"event_id": "a"}], "total_count": 2}),
            _resp(200, {"events": [{"event_id": "b"}], "total_count": 2}),
        )
        with patch("control_center.compliance.billing_client.httpx.AsyncClient", return_value=ctx):
            events, truncated, unavailable = await billing_client.list_all_usage_events(
                organization_id=1, start_date=date(2026, 8, 1), end_date=date(2026, 8, 31), authorization="Bearer tok",
            )
        self.assertEqual([e["event_id"] for e in events], ["a", "b"])
        self.assertFalse(truncated)
        self.assertFalse(unavailable)

    async def test_resource_filter_is_forwarded(self) -> None:
        ctx, mock_client = _mock_client(_resp(200, {"events": [], "total_count": 0}))
        with patch("control_center.compliance.billing_client.httpx.AsyncClient", return_value=ctx):
            await billing_client.list_all_usage_events(
                organization_id=1, start_date=date(2026, 8, 1), end_date=date(2026, 8, 31),
                resource="rag.query", authorization="Bearer tok",
            )
        _, kwargs = mock_client.get.call_args
        self.assertEqual(kwargs["params"]["resource"], "rag.query")

    async def test_unreachable_returns_unavailable_true_not_truncated(self) -> None:
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        with patch("control_center.compliance.billing_client.httpx.AsyncClient", return_value=mock_ctx):
            events, truncated, unavailable = await billing_client.list_all_usage_events(
                organization_id=1, start_date=date(2026, 8, 1), end_date=date(2026, 8, 31), authorization="Bearer tok",
            )
        self.assertEqual(events, [])
        self.assertFalse(truncated)
        self.assertTrue(unavailable)

    async def test_non_200_stops_and_returns_partial_flagged_unavailable(self) -> None:
        ctx, _ = _mock_client(_resp(500))
        with patch("control_center.compliance.billing_client.httpx.AsyncClient", return_value=ctx):
            events, truncated, unavailable = await billing_client.list_all_usage_events(
                organization_id=1, start_date=date(2026, 8, 1), end_date=date(2026, 8, 31), authorization="Bearer tok",
            )
        self.assertEqual(events, [])
        self.assertFalse(truncated)
        self.assertTrue(unavailable)

    async def test_failure_mid_pagination_keeps_earlier_pages_but_flags_unavailable(self) -> None:
        ctx, mock_client = _mock_client(
            _resp(200, {"events": [{"event_id": "a"}], "total_count": 5}),
            _resp(500),
        )
        with patch("control_center.compliance.billing_client.httpx.AsyncClient", return_value=ctx):
            events, truncated, unavailable = await billing_client.list_all_usage_events(
                organization_id=1, start_date=date(2026, 8, 1), end_date=date(2026, 8, 31), authorization="Bearer tok",
            )
        self.assertEqual([e["event_id"] for e in events], ["a"])
        self.assertFalse(truncated)
        self.assertTrue(unavailable)

    async def test_pagination_cap_boundary_sets_truncated_and_stops_fetching(self) -> None:
        # Exactly _MAX_PAGES (100) pages, total_count always claiming
        # more remain than the cap allows -- page 101 must never be
        # requested.
        responses = [_resp(200, {"events": [{"event_id": f"e{i}"}], "total_count": 1_000_000}) for i in range(100)]
        ctx, mock_client = _mock_client(*responses)
        with patch("control_center.compliance.billing_client.httpx.AsyncClient", return_value=ctx):
            events, truncated, unavailable = await billing_client.list_all_usage_events(
                organization_id=1, start_date=date(2026, 8, 1), end_date=date(2026, 8, 31), authorization="Bearer tok",
            )
        self.assertEqual(len(events), 100)
        self.assertTrue(truncated)
        self.assertFalse(unavailable)
        self.assertEqual(mock_client.get.call_count, 100)


if __name__ == "__main__":
    unittest.main()
