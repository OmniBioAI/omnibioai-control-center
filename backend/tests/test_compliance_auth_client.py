"""Unit tests for control_center.compliance.auth_client. Mocking shape
mirrors tests/test_analytics_billing_client.py exactly (this codebase's
established convention for testing a thin httpx client module).
"""
from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from control_center.compliance import auth_client


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


class GetOrganizationTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_returns_body_and_ok_on_success(self) -> None:
        ctx, _ = _mock_client(_resp(200, {"id": 1, "name": "KUMC Research"}))
        with patch("control_center.compliance.auth_client.httpx.AsyncClient", return_value=ctx):
            body, status = await auth_client.get_organization(1, "Bearer tok")
        self.assertEqual(body["name"], "KUMC Research")
        self.assertEqual(status, "ok")

    # Pre-merge review fix: a confirmed 404 (org genuinely doesn't exist)
    # must be distinguishable from a network/5xx failure -- they mean
    # very different things to a compliance report. Exercised by the two
    # tests immediately below.

    async def test_404_returns_not_found_status(self) -> None:
        ctx, _ = _mock_client(_resp(404))
        with patch("control_center.compliance.auth_client.httpx.AsyncClient", return_value=ctx):
            body, status = await auth_client.get_organization(1, "Bearer tok")
        self.assertIsNone(body)
        self.assertEqual(status, "not_found")

    async def test_500_returns_unavailable_status(self) -> None:
        ctx, _ = _mock_client(_resp(500))
        with patch("control_center.compliance.auth_client.httpx.AsyncClient", return_value=ctx):
            body, status = await auth_client.get_organization(1, "Bearer tok")
        self.assertIsNone(body)
        self.assertEqual(status, "unavailable")

    async def test_unreachable_returns_unavailable_status(self) -> None:
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        with patch("control_center.compliance.auth_client.httpx.AsyncClient", return_value=mock_ctx):
            body, status = await auth_client.get_organization(1, "Bearer tok")
        self.assertIsNone(body)
        self.assertEqual(status, "unavailable")


class GetOrgMembersTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_returns_member_list_and_ok(self) -> None:
        ctx, _ = _mock_client(_resp(200, [{"user_id": 1, "email": "a@kumc.edu", "status": "active", "roles": ["member"]}]))
        with patch("control_center.compliance.auth_client.httpx.AsyncClient", return_value=ctx):
            members, status = await auth_client.get_org_members(1, "Bearer tok")
        self.assertEqual(members[0]["email"], "a@kumc.edu")
        self.assertEqual(status, "ok")

    async def test_empty_list_and_not_found_on_404(self) -> None:
        ctx, _ = _mock_client(_resp(404))
        with patch("control_center.compliance.auth_client.httpx.AsyncClient", return_value=ctx):
            members, status = await auth_client.get_org_members(1, "Bearer tok")
        self.assertEqual(members, [])
        self.assertEqual(status, "not_found")

    async def test_empty_list_and_unavailable_on_failure(self) -> None:
        ctx, _ = _mock_client(_resp(403))
        with patch("control_center.compliance.auth_client.httpx.AsyncClient", return_value=ctx):
            members, status = await auth_client.get_org_members(1, "Bearer tok")
        self.assertEqual(members, [])
        self.assertEqual(status, "unavailable")

    async def test_non_list_body_returns_unavailable(self) -> None:
        # A malformed/unexpected 200 body must not be silently treated as
        # "zero members" -- that's indistinguishable from a real empty
        # org otherwise.
        ctx, _ = _mock_client(_resp(200, {"unexpected": "shape"}))
        with patch("control_center.compliance.auth_client.httpx.AsyncClient", return_value=ctx):
            members, status = await auth_client.get_org_members(1, "Bearer tok")
        self.assertEqual(members, [])
        self.assertEqual(status, "unavailable")


class ListAllAuditEventsTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_single_page_stops_after_total_pages(self) -> None:
        ctx, mock_client = _mock_client(_resp(200, {"items": [{"id": 1}], "total_pages": 1}))
        with patch("control_center.compliance.auth_client.httpx.AsyncClient", return_value=ctx):
            items, truncated, unavailable = await auth_client.list_all_audit_events(
                organization_id=1, start_date=datetime(2026, 8, 1), end_date=datetime(2026, 8, 31),
                authorization="Bearer tok",
            )
        self.assertEqual(len(items), 1)
        self.assertFalse(truncated)
        self.assertFalse(unavailable)
        self.assertEqual(mock_client.get.call_count, 1)

    async def test_follows_pagination_across_multiple_pages(self) -> None:
        ctx, mock_client = _mock_client(
            _resp(200, {"items": [{"id": 1}], "total_pages": 2}),
            _resp(200, {"items": [{"id": 2}], "total_pages": 2}),
        )
        with patch("control_center.compliance.auth_client.httpx.AsyncClient", return_value=ctx):
            items, truncated, unavailable = await auth_client.list_all_audit_events(
                organization_id=1, start_date=datetime(2026, 8, 1), end_date=datetime(2026, 8, 31),
                authorization="Bearer tok",
            )
        self.assertEqual([i["id"] for i in items], [1, 2])
        self.assertFalse(truncated)
        self.assertFalse(unavailable)

    async def test_organization_id_none_omits_param(self) -> None:
        ctx, mock_client = _mock_client(_resp(200, {"items": [], "total_pages": 0}))
        with patch("control_center.compliance.auth_client.httpx.AsyncClient", return_value=ctx):
            await auth_client.list_all_audit_events(
                organization_id=None, start_date=datetime(2026, 8, 1), end_date=datetime(2026, 8, 31),
                authorization="Bearer tok",
            )
        _, kwargs = mock_client.get.call_args
        self.assertNotIn("organization_id", kwargs["params"])

    async def test_event_type_filter_is_forwarded(self) -> None:
        ctx, mock_client = _mock_client(_resp(200, {"items": [], "total_pages": 0}))
        with patch("control_center.compliance.auth_client.httpx.AsyncClient", return_value=ctx):
            await auth_client.list_all_audit_events(
                organization_id=1, start_date=datetime(2026, 8, 1), end_date=datetime(2026, 8, 31),
                event_type="login_success", authorization="Bearer tok",
            )
        _, kwargs = mock_client.get.call_args
        self.assertEqual(kwargs["params"]["event_type"], "login_success")

    async def test_unreachable_returns_unavailable_true_not_truncated(self) -> None:
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        with patch("control_center.compliance.auth_client.httpx.AsyncClient", return_value=mock_ctx):
            items, truncated, unavailable = await auth_client.list_all_audit_events(
                organization_id=1, start_date=datetime(2026, 8, 1), end_date=datetime(2026, 8, 31),
                authorization="Bearer tok",
            )
        self.assertEqual(items, [])
        self.assertFalse(truncated)
        self.assertTrue(unavailable)

    async def test_failure_mid_pagination_keeps_earlier_pages_but_flags_unavailable(self) -> None:
        ctx, mock_client = _mock_client(
            _resp(200, {"items": [{"id": 1}], "total_pages": 3}),
            _resp(500),
        )
        with patch("control_center.compliance.auth_client.httpx.AsyncClient", return_value=ctx):
            items, truncated, unavailable = await auth_client.list_all_audit_events(
                organization_id=1, start_date=datetime(2026, 8, 1), end_date=datetime(2026, 8, 31),
                authorization="Bearer tok",
            )
        # Page 1's item is real data, kept -- but the caller must not treat
        # this as a complete, reliable result.
        self.assertEqual([i["id"] for i in items], [1])
        self.assertFalse(truncated)
        self.assertTrue(unavailable)

    async def test_pagination_cap_boundary_sets_truncated_and_stops_fetching(self) -> None:
        # Exactly _MAX_PAGES (100) pages, each claiming more pages exist
        # than the cap allows -- the 101st page must never be requested.
        responses = [_resp(200, {"items": [{"id": i}], "total_pages": 200}) for i in range(100)]
        ctx, mock_client = _mock_client(*responses)
        with patch("control_center.compliance.auth_client.httpx.AsyncClient", return_value=ctx):
            items, truncated, unavailable = await auth_client.list_all_audit_events(
                organization_id=1, start_date=datetime(2026, 8, 1), end_date=datetime(2026, 8, 31),
                authorization="Bearer tok",
            )
        self.assertEqual(len(items), 100)
        self.assertTrue(truncated)
        self.assertFalse(unavailable)
        self.assertEqual(mock_client.get.call_count, 100)


if __name__ == "__main__":
    unittest.main()
