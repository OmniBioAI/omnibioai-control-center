"""Unit tests for control_center.compliance.billing_client.
list_all_usage_events(): paginates via offset until total_count is
reached or the _MAX_PAGES cap is hit (never requesting one page beyond
the cap), forwards the optional resource filter, and distinguishes
truncated (hit the page cap, partial-but-not-a-failure) from unavailable
(a connection error or non-200 mid-fetch, partial-and-degraded), keeping
whatever events were already fetched in either case.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""
from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from control_center.compliance import billing_client


def _resp(status_code: int, json_body=None) -> MagicMock:
    """A MagicMock httpx.Response stand-in with a fixed status/JSON body."""
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_body
    return r


def _mock_client(*responses: MagicMock):
    """An async-context-manager mock of httpx.AsyncClient whose .get()
    returns each of `responses` in order (a single response is returned
    every call; multiple are consumed one per call, for pagination)."""
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
    """list_all_usage_events()'s pagination loop, its (events, truncated,
    unavailable) return contract, and the page-count cap."""

    async def test_single_page_stops_when_offset_reaches_total(self) -> None:
        """A single page whose event count already equals total_count
        makes exactly one request and returns not truncated/unavailable."""
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
        """When total_count exceeds the first page's event count, a
        second page is fetched via an advancing offset and both pages'
        events are concatenated in order."""
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
        """A `resource` argument is forwarded as a "resource" query param
        on the request."""
        ctx, mock_client = _mock_client(_resp(200, {"events": [], "total_count": 0}))
        with patch("control_center.compliance.billing_client.httpx.AsyncClient", return_value=ctx):
            await billing_client.list_all_usage_events(
                organization_id=1, start_date=date(2026, 8, 1), end_date=date(2026, 8, 31),
                resource="rag.query", authorization="Bearer tok",
            )
        _, kwargs = mock_client.get.call_args
        self.assertEqual(kwargs["params"]["resource"], "rag.query")

    async def test_unreachable_returns_unavailable_true_not_truncated(self) -> None:
        """A connection failure on the first request returns an empty
        event list with unavailable=True and truncated=False."""
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
        """A non-200 response on the first request stops fetching and
        returns unavailable=True with an empty event list."""
        ctx, _ = _mock_client(_resp(500))
        with patch("control_center.compliance.billing_client.httpx.AsyncClient", return_value=ctx):
            events, truncated, unavailable = await billing_client.list_all_usage_events(
                organization_id=1, start_date=date(2026, 8, 1), end_date=date(2026, 8, 31), authorization="Bearer tok",
            )
        self.assertEqual(events, [])
        self.assertFalse(truncated)
        self.assertTrue(unavailable)

    async def test_failure_mid_pagination_keeps_earlier_pages_but_flags_unavailable(self) -> None:
        """A failure on the second page keeps the first page's already-
        fetched events and still flags unavailable=True, not truncated."""
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
        """With total_count always claiming far more events remain than
        _MAX_PAGES (100) allows, exactly 100 requests are made, page 101
        is never requested, and the result is truncated=True,
        unavailable=False."""
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
