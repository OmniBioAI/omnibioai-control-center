"""
tests/test_routes_billing_proxy.py

Unit tests for:
  - control_center.api.routes_billing_proxy
    (GET /billing/organizations/{organization_id}/summary,
    GET /billing/organizations/{organization_id}/invoices,
    GET /billing/organizations/{organization_id}/cost-breakdown,
    GET /billing/invoices/{invoice_id},
    GET /billing/invoices/{invoice_id}/line-items)

Mirrors test_routes_org_sso_proxy.py's exact conventions -- these routes
are a thin relay, no authorization decision is made here (that's
entirely omnibioai-billing's own job, via app.core.iam.
get_authorized_organization_id/get_authorized_invoice, both pre-existing
from PR14.4F/PR14.5C and unmodified by this proxy). All five routes are
GET-only, so unlike test_routes_org_sso_proxy.py there is no body-
forwarding or 204-empty-body case to cover here.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi.testclient import TestClient

from control_center.main import app

client = TestClient(app)


def _mock_response(status_code: int, json_body=None, raise_json_error: bool = False) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    if raise_json_error:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = json_body
    return resp


def _mock_async_client(response: MagicMock = None, side_effect=None):
    mock_client = MagicMock()
    mock_get = AsyncMock()
    if side_effect is not None:
        mock_get.side_effect = side_effect
    else:
        mock_get.return_value = response
    mock_client.get = mock_get

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


_USAGE_OUT = {
    "organization_id": 7,
    "period_start": "2026-08-01",
    "period_end": "2026-08-31",
    "services": [
        {"service": "tes", "action": "run", "resource": "compute_minutes", "unit": "minutes", "quantity": "120.0"},
    ],
}

_SUMMARY_OUT = {
    "organization_id": 7,
    "current_period": None,
    "invoice_count": 2,
    "outstanding_amount": "10.00",
}

_INVOICE_LIST_OUT = {"invoices": [], "total": 0, "limit": 50, "offset": 0}

_INVOICE_DETAIL_OUT = {
    "id": 99,
    "organization_id": 7,
    "status": "DRAFT",
    "total": "10.00",
    "line_items": [],
}

_LINE_ITEMS_OUT = {"line_items": [], "total": 0, "limit": 50, "offset": 0}

_COST_BREAKDOWN_OUT = {"organization_id": 7, "group_by": "service", "entries": []}

_SUBSCRIPTION_OUT = {
    "organization_id": 7,
    "billing_plan_id": 1,
    "plan_name": "Enterprise",
    "billing_interval": "monthly",
    "currency": "usd",
    "status": "active",
    "start_date": "2026-01-01",
    "end_date": None,
    "renewal_date": "2026-02-01",
    "features": [],
}

_USAGE_LIMITS_OUT = {
    "organization_id": 7,
    "billing_plan_id": 1,
    "plan_name": "Enterprise",
    "as_of": "2026-01-15",
    "limits": [],
}


class TestOrganizationUsageProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _USAGE_OUT)
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/billing/organizations/7/usage", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["services"][0]["service"], "tes")

    def test_forwards_authorization_header(self) -> None:
        upstream = _mock_response(200, _USAGE_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/billing/organizations/7/usage", headers={"Authorization": "Bearer my-token-123"})
        call_kwargs = mock_ctx.__aenter__.return_value.get.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer my-token-123")

    def test_forwards_organization_id_in_path(self) -> None:
        upstream = _mock_response(200, _USAGE_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/billing/organizations/42/usage", headers={"Authorization": "Bearer tok"})
        call_args = mock_ctx.__aenter__.return_value.get.call_args
        self.assertTrue(call_args.args[0].endswith("/billing/organizations/42/usage"))

    def test_forwards_403_for_wrong_organization(self) -> None:
        upstream = _mock_response(403, {"detail": "Not authorized for this organization"})
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/billing/organizations/7/usage", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)

    def test_billing_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_billing_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/billing/organizations/7/usage", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 503)
        self.assertIn("billing-service unreachable", resp.json()["error"])

    def test_non_json_upstream_response_handled(self) -> None:
        upstream = _mock_response(500, raise_json_error=True)
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/billing/organizations/7/usage", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 500)
        self.assertIn("non-JSON", resp.json()["error"])


class TestOrganizationBillingSummaryProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _SUMMARY_OUT)
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/billing/organizations/7/summary", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["organization_id"], 7)

    def test_forwards_authorization_header(self) -> None:
        upstream = _mock_response(200, _SUMMARY_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/billing/organizations/7/summary", headers={"Authorization": "Bearer my-token-123"})
        call_kwargs = mock_ctx.__aenter__.return_value.get.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer my-token-123")

    def test_forwards_organization_id_in_path(self) -> None:
        upstream = _mock_response(200, _SUMMARY_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/billing/organizations/42/summary", headers={"Authorization": "Bearer tok"})
        call_args = mock_ctx.__aenter__.return_value.get.call_args
        self.assertTrue(call_args.args[0].endswith("/billing/organizations/42/summary"))

    def test_forwards_403_for_wrong_organization(self) -> None:
        upstream = _mock_response(403, {"detail": "Not authorized for this organization"})
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/billing/organizations/7/summary", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)

    def test_billing_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_billing_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/billing/organizations/7/summary", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 503)
        self.assertIn("billing-service unreachable", resp.json()["error"])

    def test_non_json_upstream_response_handled(self) -> None:
        upstream = _mock_response(500, raise_json_error=True)
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/billing/organizations/7/summary", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 500)
        self.assertIn("non-JSON", resp.json()["error"])


class TestListOrganizationInvoicesProxy(unittest.TestCase):
    def test_forwards_success_response_and_query_params(self) -> None:
        upstream = _mock_response(200, _INVOICE_LIST_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get(
                "/billing/organizations/7/invoices?status=PAID&limit=10",
                headers={"Authorization": "Bearer tok"},
            )
        self.assertEqual(resp.status_code, 200)
        call_kwargs = mock_ctx.__aenter__.return_value.get.call_args.kwargs
        self.assertEqual(call_kwargs["params"]["status"], "PAID")
        self.assertEqual(call_kwargs["params"]["limit"], "10")

    def test_forwards_404_for_missing_organization(self) -> None:
        upstream = _mock_response(404, {"detail": "Not found"})
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/billing/organizations/7/invoices", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)


class TestOrganizationCostBreakdownProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _COST_BREAKDOWN_OUT)
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get(
                "/billing/organizations/7/cost-breakdown?start_date=2026-08-01&end_date=2026-08-31&group_by=service",
                headers={"Authorization": "Bearer tok"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["group_by"], "service")

    def test_forwards_422_for_invalid_group_by(self) -> None:
        upstream = _mock_response(422, {"detail": "invalid group_by"})
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get(
                "/billing/organizations/7/cost-breakdown?start_date=2026-08-01&end_date=2026-08-31&group_by=bogus",
                headers={"Authorization": "Bearer tok"},
            )
        self.assertEqual(resp.status_code, 422)


class TestInvoiceDetailProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _INVOICE_DETAIL_OUT)
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/billing/invoices/99", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], 99)

    def test_forwards_invoice_id_in_path(self) -> None:
        upstream = _mock_response(200, _INVOICE_DETAIL_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/billing/invoices/123", headers={"Authorization": "Bearer tok"})
        call_args = mock_ctx.__aenter__.return_value.get.call_args
        self.assertTrue(call_args.args[0].endswith("/billing/invoices/123"))

    def test_forwards_404_when_not_found_or_wrong_org(self) -> None:
        # get_authorized_invoice returns 404 (not 403) for a wrong-org
        # invoice, by design -- this proxy just relays whichever status
        # the billing service returns.
        upstream = _mock_response(404, {"detail": "Invoice not found"})
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/billing/invoices/99", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)


class TestInvoiceLineItemsProxy(unittest.TestCase):
    def test_forwards_success_response_and_pagination_params(self) -> None:
        upstream = _mock_response(200, _LINE_ITEMS_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get(
                "/billing/invoices/99/line-items?limit=25&offset=25",
                headers={"Authorization": "Bearer tok"},
            )
        self.assertEqual(resp.status_code, 200)
        call_kwargs = mock_ctx.__aenter__.return_value.get.call_args.kwargs
        self.assertEqual(call_kwargs["params"]["limit"], "25")
        self.assertEqual(call_kwargs["params"]["offset"], "25")

    def test_forwards_404_when_not_found(self) -> None:
        upstream = _mock_response(404, {"detail": "Invoice not found"})
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/billing/invoices/99/line-items", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)


class TestOrganizationSubscriptionProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _SUBSCRIPTION_OUT)
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/billing/organizations/7/subscription", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["plan_name"], "Enterprise")

    def test_forwards_organization_id_in_path(self) -> None:
        upstream = _mock_response(200, _SUBSCRIPTION_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/billing/organizations/42/subscription", headers={"Authorization": "Bearer tok"})
        call_args = mock_ctx.__aenter__.return_value.get.call_args
        self.assertTrue(call_args.args[0].endswith("/billing/organizations/42/subscription"))

    def test_forwards_404_when_no_active_subscription(self) -> None:
        upstream = _mock_response(404, {"detail": "organization_id=7 has no active subscription"})
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/billing/organizations/7/subscription", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)

    def test_billing_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_billing_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/billing/organizations/7/subscription", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 503)


class TestOrganizationSubscriptionUsageLimitsProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _USAGE_LIMITS_OUT)
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/billing/organizations/7/subscription/usage-limits", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["limits"], [])

    def test_forwards_as_of_query_param(self) -> None:
        upstream = _mock_response(200, _USAGE_LIMITS_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get(
                "/billing/organizations/7/subscription/usage-limits?as_of=2026-01-15",
                headers={"Authorization": "Bearer tok"},
            )
        call_kwargs = mock_ctx.__aenter__.return_value.get.call_args.kwargs
        self.assertEqual(call_kwargs["params"]["as_of"], "2026-01-15")

    def test_forwards_404_when_no_active_subscription(self) -> None:
        upstream = _mock_response(404, {"detail": "organization_id=7 has no active subscription"})
        with patch("control_center.api.routes_billing_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/billing/organizations/7/subscription/usage-limits", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
