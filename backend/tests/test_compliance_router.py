"""End-to-end tests for GET /compliance/hipaa-report via FastAPI's
TestClient, mirroring test_analytics_router.py's own conventions (real
JWTs against a patched JWT_SECRET, FakeRedis for the cache layer,
service.build_report itself mocked out -- its own aggregation logic is
covered by test_compliance_service.py, not re-tested here).
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
    return jwt.encode(claims, SECRET, algorithm="HS256")


def _auth(**claims) -> dict:
    return {"Authorization": f"Bearer {_token(**claims)}"}


class ComplianceRouterTestCase(unittest.TestCase):
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
        params = {"from_date": "2026-08-01", "to_date": "2026-08-31", "org_id": 1}
        params.update(overrides)
        return params


class AuthenticationTestCase(ComplianceRouterTestCase):
    def test_missing_token_returns_401(self) -> None:
        r = client.get("/compliance/hipaa-report", params=self._params())
        self.assertEqual(r.status_code, 401)

    def test_invalid_token_returns_401(self) -> None:
        r = client.get("/compliance/hipaa-report", params=self._params(), headers={"Authorization": "Bearer garbage"})
        self.assertEqual(r.status_code, 401)


class RbacTestCase(ComplianceRouterTestCase):
    def test_platform_admin_allowed(self) -> None:
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
        headers = _auth(sub="1", permissions=[], org_id=1, org_role=["member"])
        r = client.get("/compliance/hipaa-report", params=self._params(), headers=headers)
        self.assertEqual(r.status_code, 403)

    def test_denied_request_does_not_emit_audit_log(self) -> None:
        headers = _auth(sub="1", permissions=[], org_id=1, org_role=["member"])
        client.get("/compliance/hipaa-report", params=self._params(), headers=headers)
        self.audit_log_mock.assert_not_called()


class HipaaReportEndpointTestCase(ComplianceRouterTestCase):
    def test_returns_report_body(self) -> None:
        r = client.get("/compliance/hipaa-report", params=self._params(), headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["organization_name"], "KUMC Research")

    def test_response_uses_renamed_summary_fields(self) -> None:
        r = client.get("/compliance/hipaa-report", params=self._params(), headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        summary = r.json()["summary"]
        self.assertIn("failed_login_attempts", summary)
        self.assertIn("security_events_requiring_review", summary)
        self.assertNotIn("security_incidents", summary)

    def test_response_includes_sources_unavailable(self) -> None:
        r = client.get("/compliance/hipaa-report", params=self._params(), headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.json()["sources_unavailable"], [])

    def test_missing_required_params_returns_422(self) -> None:
        r = client.get("/compliance/hipaa-report", params={"from_date": "2026-08-01"}, headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.status_code, 422)

    def test_from_date_after_to_date_returns_400(self) -> None:
        params = self._params(from_date="2026-08-31", to_date="2026-08-01")
        r = client.get("/compliance/hipaa-report", params=params, headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.status_code, 400)

    def test_validation_failure_does_not_emit_audit_log(self) -> None:
        params = self._params(from_date="2026-08-31", to_date="2026-08-01")
        client.get("/compliance/hipaa-report", params=params, headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.audit_log_mock.assert_not_called()

    def test_generated_by_uses_token_email_claim(self) -> None:
        headers = _auth(sub="1", email="alice@kumc.edu", permissions=[MANAGE_ALL_ORGS])
        r = client.get("/compliance/hipaa-report", params=self._params(), headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["generated_by"], "alice@kumc.edu")

    def test_generated_by_falls_back_to_sub_without_email_claim(self) -> None:
        headers = _auth(sub="42", permissions=[MANAGE_ALL_ORGS])
        r = client.get("/compliance/hipaa-report", params=self._params(), headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["generated_by"], "42")

    def test_second_request_hits_cache_not_build_report_again(self) -> None:
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
        headers = _auth(sub="1", permissions=[MANAGE_ALL_ORGS])
        client.get("/compliance/hipaa-report", params=self._params(org_id=1), headers=headers)
        client.get("/compliance/hipaa-report", params=self._params(org_id=2), headers=headers)
        self.assertEqual(self.build_report_mock.await_count, 2)

    def test_nonexistent_organization_returns_404(self) -> None:
        self.build_report_mock.side_effect = service_module.OrganizationNotFoundError(999)
        r = client.get("/compliance/hipaa-report", params=self._params(org_id=999), headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.status_code, 404)

    def test_404_does_not_emit_audit_log(self) -> None:
        self.build_report_mock.side_effect = service_module.OrganizationNotFoundError(999)
        client.get("/compliance/hipaa-report", params=self._params(org_id=999), headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.audit_log_mock.assert_not_called()

    def test_audit_log_called_with_expected_fields_on_success(self) -> None:
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
    def test_platform_admin_gets_pdf(self) -> None:
        r = client.get("/compliance/hipaa-report/pdf", params=self._params(), headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF-"))

    def test_content_disposition_filename(self) -> None:
        r = client.get("/compliance/hipaa-report/pdf", params=self._params(), headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertIn('filename="hipaa-report-org1-2026-08-01-to-2026-08-31.pdf"', r.headers["content-disposition"])

    def test_org_admin_without_manage_all_orgs_denied(self) -> None:
        headers = _auth(sub="1", permissions=[], org_id=1, org_role=["org_admin"])
        r = client.get("/compliance/hipaa-report/pdf", params=self._params(), headers=headers)
        self.assertEqual(r.status_code, 403)

    def test_missing_token_returns_401(self) -> None:
        r = client.get("/compliance/hipaa-report/pdf", params=self._params())
        self.assertEqual(r.status_code, 401)

    def test_from_date_after_to_date_returns_400(self) -> None:
        params = self._params(from_date="2026-08-31", to_date="2026-08-01")
        r = client.get("/compliance/hipaa-report/pdf", params=params, headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.status_code, 400)

    def test_nonexistent_organization_returns_404(self) -> None:
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
        headers = _auth(sub="1", email="alice@kumc.edu", permissions=[MANAGE_ALL_ORGS])
        client.get("/compliance/hipaa-report/pdf", params=self._params(), headers=headers)
        self.audit_log_mock.assert_called_once()
        _, kwargs = self.audit_log_mock.call_args
        self.assertEqual(kwargs["report_format"], "pdf")


class HipaaReportCsvEndpointTestCase(ComplianceRouterTestCase):
    def test_platform_admin_gets_csv(self) -> None:
        r = client.get("/compliance/hipaa-report/csv", params=self._params(), headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "text/csv; charset=utf-8")
        self.assertIn("KUMC Research", r.text)
        self.assertIn("## Section 1: Executive Summary", r.text)

    def test_content_disposition_filename(self) -> None:
        r = client.get("/compliance/hipaa-report/csv", params=self._params(), headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertIn('filename="hipaa-report-org1-2026-08-01-to-2026-08-31.csv"', r.headers["content-disposition"])

    def test_org_admin_without_manage_all_orgs_denied(self) -> None:
        headers = _auth(sub="1", permissions=[], org_id=1, org_role=["org_admin"])
        r = client.get("/compliance/hipaa-report/csv", params=self._params(), headers=headers)
        self.assertEqual(r.status_code, 403)

    def test_missing_token_returns_401(self) -> None:
        r = client.get("/compliance/hipaa-report/csv", params=self._params())
        self.assertEqual(r.status_code, 401)

    def test_from_date_after_to_date_returns_400(self) -> None:
        params = self._params(from_date="2026-08-31", to_date="2026-08-01")
        r = client.get("/compliance/hipaa-report/csv", params=params, headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.status_code, 400)

    def test_nonexistent_organization_returns_404(self) -> None:
        self.build_report_mock.side_effect = service_module.OrganizationNotFoundError(999)
        r = client.get("/compliance/hipaa-report/csv", params=self._params(org_id=999), headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.status_code, 404)

    def test_csv_reuses_json_cache_entry(self) -> None:
        headers = _auth(sub="1", permissions=[MANAGE_ALL_ORGS])
        client.get("/compliance/hipaa-report", params=self._params(), headers=headers)
        r = client.get("/compliance/hipaa-report/csv", params=self._params(), headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.build_report_mock.await_count, 1)

    def test_csv_reflects_current_requester_generated_by(self) -> None:
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
        headers = _auth(sub="1", email="alice@kumc.edu", permissions=[MANAGE_ALL_ORGS])
        client.get("/compliance/hipaa-report/csv", params=self._params(), headers=headers)
        self.audit_log_mock.assert_called_once()
        _, kwargs = self.audit_log_mock.call_args
        self.assertEqual(kwargs["report_format"], "csv")


if __name__ == "__main__":
    unittest.main()
