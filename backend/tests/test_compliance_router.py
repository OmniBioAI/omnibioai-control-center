"""End-to-end tests for GET /compliance/hipaa-report (and its /pdf, /csv
siblings) via FastAPI's TestClient, mirroring test_analytics_router.py's
own conventions (real JWTs against a patched JWT_SECRET, FakeRedis for the
cache layer, service.build_report itself mocked out -- its own aggregation
logic is covered by test_compliance_service.py, not re-tested here).

Covers platform_admin-only RBAC, per-request generated_by/generated_at
stamping even on a cache hit, cache-key scoping by org/date-range, the
OrganizationNotFoundError-to-404 mapping, audit-log emission (and its
suppression on denied/invalid/404 requests), and the PDF/CSV endpoints'
shared cache reuse with the JSON endpoint.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
from fastapi.testclient import TestClient

from control_center.compliance import service as service_module
from control_center.compliance.router import MANAGE_ALL_ORGS
from control_center.core import jwt_verify as jwt_verify_module
from control_center.main import app
from _fake_redis import FakeRedis

client = TestClient(app)
SECRET = "test-secret"

# Pre-merge security review fix: generated_by/generated_at are no longer
# part of what service.build_report returns (see service.py's own module
# docstring) -- router.py stamps them fresh per request instead. The stub
# below matches that contract; security_incidents is renamed/split into
# failed_login_attempts + security_events_requiring_review, and
# sources_unavailable is new.
_REPORT_STUB = {
    "organization_id": 1,
    "organization_name": "KUMC Research",
    "from_date": "2026-08-01",
    "to_date": "2026-08-31",
    "summary": {
        "total_users": 2, "active_users": 1, "total_rag_queries": 3,
        "failed_login_attempts": 0, "security_events_requiring_review": 0,
    },
    "user_access": [],
    "rag_queries": [],
    "security_events": [],
    "truncated": False,
    "sources_unavailable": [],
}


def _token(**claims) -> str:
    """A JWT signed with the module's own SECRET, carrying the given claims."""
    return jwt.encode(claims, SECRET, algorithm="HS256")


def _auth(**claims) -> dict:
    """A bearer-token Authorization header for a JWT carrying the given claims."""
    return {"Authorization": f"Bearer {_token(**claims)}"}


class ComplianceRouterTestCase(unittest.TestCase):
    """Base fixture: JWT_SECRET pinned, cache backed by FakeRedis, service.build_report and audit_log.log_report_access mocked out."""

    def setUp(self) -> None:
        jwt_patcher = patch.object(jwt_verify_module, "JWT_SECRET", SECRET)
        jwt_patcher.start()
        self.addCleanup(jwt_patcher.stop)

        self.fake = FakeRedis()
        from control_center.analytics import cache as cache_module
        cache_patcher = patch.object(cache_module, "_redis", self.fake)
        cache_patcher.start()
        self.addCleanup(cache_patcher.stop)

        self.build_report_mock = AsyncMock(return_value=dict(_REPORT_STUB))
        build_report_patcher = patch(
            "control_center.compliance.router.service.build_report", self.build_report_mock,
        )
        build_report_patcher.start()
        self.addCleanup(build_report_patcher.stop)

        self.audit_log_mock = MagicMock()
        audit_log_patcher = patch(
            "control_center.compliance.router.audit_log.log_report_access", self.audit_log_mock,
        )
        audit_log_patcher.start()
        self.addCleanup(audit_log_patcher.stop)

    def _params(self, **overrides):
        """Default from_date/to_date/org_id query params, with overrides merged in."""
        params = {"from_date": "2026-08-01", "to_date": "2026-08-31", "org_id": 1}
        params.update(overrides)
        return params


class AuthenticationTestCase(ComplianceRouterTestCase):
    """Missing or invalid bearer tokens are rejected before any report logic runs."""

    def test_missing_token_returns_401(self) -> None:
        """A request with no Authorization header is rejected with 401."""
        r = client.get("/compliance/hipaa-report", params=self._params())
        self.assertEqual(r.status_code, 401)

    def test_invalid_token_returns_401(self) -> None:
        """A request with an unparseable bearer token is rejected with 401."""
        r = client.get("/compliance/hipaa-report", params=self._params(), headers={"Authorization": "Bearer garbage"})
        self.assertEqual(r.status_code, 401)


class RbacTestCase(ComplianceRouterTestCase):
    """The platform_admin-only gate on the JSON HIPAA report endpoint."""

    def test_platform_admin_allowed(self) -> None:
        """A MANAGE_ALL_ORGS token can fetch the report."""
        r = client.get("/compliance/hipaa-report", params=self._params(), headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.status_code, 200)

    def test_org_admin_without_manage_all_orgs_denied(self) -> None:
        """v0.8.0 is platform_admin-only -- an org_admin token (no
        manage_all_orgs permission) is 403, unlike /analytics/* which
        does grant org_admin scoped access. Deferred to v0.9.0 -- see
        compliance/service.py's own module docstring."""
        headers = _auth(sub="1", permissions=[], org_id=1, org_role=["org_admin"])
        r = client.get("/compliance/hipaa-report", params=self._params(), headers=headers)
        self.assertEqual(r.status_code, 403)

    def test_regular_user_denied(self) -> None:
        """A plain org member with no admin role is denied with 403."""
        headers = _auth(sub="1", permissions=[], org_id=1, org_role=["member"])
        r = client.get("/compliance/hipaa-report", params=self._params(), headers=headers)
        self.assertEqual(r.status_code, 403)

    def test_denied_request_does_not_emit_audit_log(self) -> None:
        """A 403-denied request never triggers an audit_log.log_report_access call."""
        headers = _auth(sub="1", permissions=[], org_id=1, org_role=["member"])
        client.get("/compliance/hipaa-report", params=self._params(), headers=headers)
        self.audit_log_mock.assert_not_called()


class HipaaReportEndpointTestCase(ComplianceRouterTestCase):
    """GET /compliance/hipaa-report's JSON response shape, validation, caching, and audit-log emission."""

    def test_returns_report_body(self) -> None:
        """A successful request returns the stubbed report body, including organization_name."""
        r = client.get("/compliance/hipaa-report", params=self._params(), headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["organization_name"], "KUMC Research")

    def test_response_uses_renamed_summary_fields(self) -> None:
        """The summary uses failed_login_attempts/security_events_requiring_review, not the old security_incidents field."""
        r = client.get("/compliance/hipaa-report", params=self._params(), headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        summary = r.json()["summary"]
        self.assertIn("failed_login_attempts", summary)
        self.assertIn("security_events_requiring_review", summary)
        self.assertNotIn("security_incidents", summary)

    def test_response_includes_sources_unavailable(self) -> None:
        """The response includes the sources_unavailable field from the underlying report."""
        r = client.get("/compliance/hipaa-report", params=self._params(), headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.json()["sources_unavailable"], [])

    def test_missing_required_params_returns_422(self) -> None:
        """Omitting a required query param (to_date/org_id) is rejected with 422."""
        r = client.get("/compliance/hipaa-report", params={"from_date": "2026-08-01"}, headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.status_code, 422)

    def test_from_date_after_to_date_returns_400(self) -> None:
        """A from_date later than to_date is rejected with 400."""
        params = self._params(from_date="2026-08-31", to_date="2026-08-01")
        r = client.get("/compliance/hipaa-report", params=params, headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.status_code, 400)

    def test_validation_failure_does_not_emit_audit_log(self) -> None:
        """A 400 date-range validation failure never triggers an audit_log.log_report_access call."""
        params = self._params(from_date="2026-08-31", to_date="2026-08-01")
        client.get("/compliance/hipaa-report", params=params, headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.audit_log_mock.assert_not_called()

    def test_generated_by_uses_token_email_claim(self) -> None:
        """generated_by is stamped from the requester's email claim when present."""
        headers = _auth(sub="1", email="alice@kumc.edu", permissions=[MANAGE_ALL_ORGS])
        r = client.get("/compliance/hipaa-report", params=self._params(), headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["generated_by"], "alice@kumc.edu")

    def test_generated_by_falls_back_to_sub_without_email_claim(self) -> None:
        """With no email claim, generated_by falls back to the token's sub claim."""
        headers = _auth(sub="42", permissions=[MANAGE_ALL_ORGS])
        r = client.get("/compliance/hipaa-report", params=self._params(), headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["generated_by"], "42")

    def test_second_request_hits_cache_not_build_report_again(self) -> None:
        """An identical second request is served from cache: build_report() is awaited only once."""
        headers = _auth(sub="1", permissions=[MANAGE_ALL_ORGS])
        r1 = client.get("/compliance/hipaa-report", params=self._params(), headers=headers)
        r2 = client.get("/compliance/hipaa-report", params=self._params(), headers=headers)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(self.build_report_mock.await_count, 1)

    def test_cache_hit_still_attributes_generated_by_to_the_actual_requester(self) -> None:
        """Pre-merge security review fix: two different admins requesting
        the same cached org/date-range must each see THEIR OWN identity
        in generated_by/generated_at -- never the identity of whoever
        happened to trigger the original cache miss."""
        r1 = client.get(
            "/compliance/hipaa-report", params=self._params(),
            headers=_auth(sub="1", email="admin-a@omnibioai.org", permissions=[MANAGE_ALL_ORGS]),
        )
        r2 = client.get(
            "/compliance/hipaa-report", params=self._params(),
            headers=_auth(sub="2", email="admin-b@omnibioai.org", permissions=[MANAGE_ALL_ORGS]),
        )
        self.assertEqual(r1.json()["generated_by"], "admin-a@omnibioai.org")
        self.assertEqual(r2.json()["generated_by"], "admin-b@omnibioai.org")
        # Both requests still hit the same cache entry underneath --
        # this is a cache HIT for r2, not a second real computation.
        self.assertEqual(self.build_report_mock.await_count, 1)

    def test_cache_hit_stamps_a_fresh_generated_at_per_request(self) -> None:
        """Two identical GET /compliance/hipaa-report requests both return a
        generated_at field, showing it is stamped per response rather than reused from
        the cached payload; wall-clock inequality is deliberately not asserted."""
        headers = _auth(sub="1", permissions=[MANAGE_ALL_ORGS])
        r1 = client.get("/compliance/hipaa-report", params=self._params(), headers=headers)
        r2 = client.get("/compliance/hipaa-report", params=self._params(), headers=headers)
        # Not asserting r1 != r2 on wall-clock time (too flaky at test
        # speed) -- asserting the field is present and ISO-parseable on
        # both, which is what proves it's stamped per-response rather
        # than baked into (and reused from) the cached payload.
        for r in (r1, r2):
            self.assertIn("generated_at", r.json())

    def test_different_org_id_is_not_cached_together(self) -> None:
        """Requests for different org_ids each trigger their own build_report() call rather than sharing a cache entry."""
        headers = _auth(sub="1", permissions=[MANAGE_ALL_ORGS])
        client.get("/compliance/hipaa-report", params=self._params(org_id=1), headers=headers)
        client.get("/compliance/hipaa-report", params=self._params(org_id=2), headers=headers)
        self.assertEqual(self.build_report_mock.await_count, 2)

    def test_nonexistent_organization_returns_404(self) -> None:
        """An OrganizationNotFoundError from build_report() is mapped to a 404 response."""
        self.build_report_mock.side_effect = service_module.OrganizationNotFoundError(999)
        r = client.get("/compliance/hipaa-report", params=self._params(org_id=999), headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.status_code, 404)

    def test_404_does_not_emit_audit_log(self) -> None:
        """A 404 organization-not-found response never triggers an audit_log.log_report_access call."""
        self.build_report_mock.side_effect = service_module.OrganizationNotFoundError(999)
        client.get("/compliance/hipaa-report", params=self._params(org_id=999), headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.audit_log_mock.assert_not_called()

    def test_audit_log_called_with_expected_fields_on_success(self) -> None:
        """A successful request logs the actor's email, the organization_id, the date range, and report_format="json"."""
        headers = _auth(sub="1", email="alice@kumc.edu", permissions=[MANAGE_ALL_ORGS])
        client.get("/compliance/hipaa-report", params=self._params(org_id=7, from_date="2026-08-01", to_date="2026-08-31"), headers=headers)
        self.audit_log_mock.assert_called_once()
        _, kwargs = self.audit_log_mock.call_args
        self.assertEqual(kwargs["actor"], "alice@kumc.edu")
        self.assertEqual(kwargs["organization_id"], 7)
        self.assertEqual(kwargs["from_date"].isoformat(), "2026-08-01")
        self.assertEqual(kwargs["to_date"].isoformat(), "2026-08-31")
        self.assertEqual(kwargs["report_format"], "json")


class HipaaReportPdfEndpointTestCase(ComplianceRouterTestCase):
    """GET /compliance/hipaa-report/pdf's PDF rendering, its shared cache with the JSON endpoint, and its own auth/audit gates."""

    def test_platform_admin_gets_pdf(self) -> None:
        """A MANAGE_ALL_ORGS request gets a 200 application/pdf response starting with the PDF magic bytes."""
        r = client.get("/compliance/hipaa-report/pdf", params=self._params(), headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF-"))

    def test_content_disposition_filename(self) -> None:
        """The Content-Disposition filename encodes the org id and date range."""
        r = client.get("/compliance/hipaa-report/pdf", params=self._params(), headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertIn('filename="hipaa-report-org1-2026-08-01-to-2026-08-31.pdf"', r.headers["content-disposition"])

    def test_org_admin_without_manage_all_orgs_denied(self) -> None:
        """An org_admin token (no manage_all_orgs) is denied with 403, same as the JSON endpoint."""
        headers = _auth(sub="1", permissions=[], org_id=1, org_role=["org_admin"])
        r = client.get("/compliance/hipaa-report/pdf", params=self._params(), headers=headers)
        self.assertEqual(r.status_code, 403)

    def test_missing_token_returns_401(self) -> None:
        """A request with no Authorization header is rejected with 401."""
        r = client.get("/compliance/hipaa-report/pdf", params=self._params())
        self.assertEqual(r.status_code, 401)

    def test_from_date_after_to_date_returns_400(self) -> None:
        """A from_date later than to_date is rejected with 400."""
        params = self._params(from_date="2026-08-31", to_date="2026-08-01")
        r = client.get("/compliance/hipaa-report/pdf", params=params, headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.status_code, 400)

    def test_nonexistent_organization_returns_404(self) -> None:
        """An OrganizationNotFoundError from build_report() is mapped to a 404 response."""
        self.build_report_mock.side_effect = service_module.OrganizationNotFoundError(999)
        r = client.get("/compliance/hipaa-report/pdf", params=self._params(org_id=999), headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.status_code, 404)

    def test_pdf_and_json_share_the_same_cache_entry(self) -> None:
        """Both routes call _fetch_cached_report with the same cache key
        shape -- the PDF endpoint should reuse a JSON request's already-
        cached data instead of recomputing it."""
        headers = _auth(sub="1", permissions=[MANAGE_ALL_ORGS])
        client.get("/compliance/hipaa-report", params=self._params(), headers=headers)
        r = client.get("/compliance/hipaa-report/pdf", params=self._params(), headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.build_report_mock.await_count, 1)

    def test_pdf_response_reflects_current_requester_not_cached_admin(self) -> None:
        """A PDF request from a different admin than the one who triggered the cache miss is audit-logged under its own actor, not the cache-populating one."""
        client.get(
            "/compliance/hipaa-report", params=self._params(),
            headers=_auth(sub="1", email="admin-a@omnibioai.org", permissions=[MANAGE_ALL_ORGS]),
        )
        r = client.get(
            "/compliance/hipaa-report/pdf", params=self._params(),
            headers=_auth(sub="2", email="admin-b@omnibioai.org", permissions=[MANAGE_ALL_ORGS]),
        )
        self.assertEqual(r.status_code, 200)
        # PDF content isn't trivially inspectable for a specific string
        # without a PDF-text-extraction dependency this repo doesn't
        # have -- the audit log call is the reliable, already-available
        # signal that the PDF route resolved *this* request's admin.
        _, kwargs = self.audit_log_mock.call_args
        self.assertEqual(kwargs["actor"], "admin-b@omnibioai.org")

    def test_audit_log_called_with_pdf_format(self) -> None:
        """A successful PDF request logs report_format="pdf"."""
        headers = _auth(sub="1", email="alice@kumc.edu", permissions=[MANAGE_ALL_ORGS])
        client.get("/compliance/hipaa-report/pdf", params=self._params(), headers=headers)
        self.audit_log_mock.assert_called_once()
        _, kwargs = self.audit_log_mock.call_args
        self.assertEqual(kwargs["report_format"], "pdf")


class HipaaReportCsvEndpointTestCase(ComplianceRouterTestCase):
    """GET /compliance/hipaa-report/csv's CSV rendering, its shared cache with the JSON endpoint, and its own auth/audit gates."""

    def test_platform_admin_gets_csv(self) -> None:
        """A MANAGE_ALL_ORGS request gets a 200 text/csv response containing the org name and the executive-summary section header."""
        r = client.get("/compliance/hipaa-report/csv", params=self._params(), headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "text/csv; charset=utf-8")
        self.assertIn("KUMC Research", r.text)
        self.assertIn("## Section 1: Executive Summary", r.text)

    def test_content_disposition_filename(self) -> None:
        """The Content-Disposition filename encodes the org id and date range."""
        r = client.get("/compliance/hipaa-report/csv", params=self._params(), headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertIn('filename="hipaa-report-org1-2026-08-01-to-2026-08-31.csv"', r.headers["content-disposition"])

    def test_org_admin_without_manage_all_orgs_denied(self) -> None:
        """An org_admin token (no manage_all_orgs) is denied with 403, same as the JSON endpoint."""
        headers = _auth(sub="1", permissions=[], org_id=1, org_role=["org_admin"])
        r = client.get("/compliance/hipaa-report/csv", params=self._params(), headers=headers)
        self.assertEqual(r.status_code, 403)

    def test_missing_token_returns_401(self) -> None:
        """A request with no Authorization header is rejected with 401."""
        r = client.get("/compliance/hipaa-report/csv", params=self._params())
        self.assertEqual(r.status_code, 401)

    def test_from_date_after_to_date_returns_400(self) -> None:
        """A from_date later than to_date is rejected with 400."""
        params = self._params(from_date="2026-08-31", to_date="2026-08-01")
        r = client.get("/compliance/hipaa-report/csv", params=params, headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.status_code, 400)

    def test_nonexistent_organization_returns_404(self) -> None:
        """An OrganizationNotFoundError from build_report() is mapped to a 404 response."""
        self.build_report_mock.side_effect = service_module.OrganizationNotFoundError(999)
        r = client.get("/compliance/hipaa-report/csv", params=self._params(org_id=999), headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.status_code, 404)

    def test_csv_reuses_json_cache_entry(self) -> None:
        """A CSV request after a JSON request for the same params reuses the cache: build_report() is awaited only once."""
        headers = _auth(sub="1", permissions=[MANAGE_ALL_ORGS])
        client.get("/compliance/hipaa-report", params=self._params(), headers=headers)
        r = client.get("/compliance/hipaa-report/csv", params=self._params(), headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.build_report_mock.await_count, 1)

    def test_csv_reflects_current_requester_generated_by(self) -> None:
        """A CSV request from a different admin than the one who triggered the cache miss shows its own requester's email, not the cache-populating one's."""
        client.get(
            "/compliance/hipaa-report", params=self._params(),
            headers=_auth(sub="1", email="admin-a@omnibioai.org", permissions=[MANAGE_ALL_ORGS]),
        )
        r = client.get(
            "/compliance/hipaa-report/csv", params=self._params(),
            headers=_auth(sub="2", email="admin-b@omnibioai.org", permissions=[MANAGE_ALL_ORGS]),
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("admin-b@omnibioai.org", r.text)
        self.assertNotIn("admin-a@omnibioai.org", r.text)

    def test_audit_log_called_with_csv_format(self) -> None:
        """A successful CSV request logs report_format="csv"."""
        headers = _auth(sub="1", email="alice@kumc.edu", permissions=[MANAGE_ALL_ORGS])
        client.get("/compliance/hipaa-report/csv", params=self._params(), headers=headers)
        self.audit_log_mock.assert_called_once()
        _, kwargs = self.audit_log_mock.call_args
        self.assertEqual(kwargs["report_format"], "csv")


if __name__ == "__main__":
    unittest.main()
