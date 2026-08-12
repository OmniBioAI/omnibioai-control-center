"""End-to-end tests for GET /compliance/hipaa-report via FastAPI's
TestClient, mirroring test_analytics_router.py's own conventions (real
JWTs against a patched JWT_SECRET, FakeRedis for the cache layer,
service.build_report itself mocked out -- its own aggregation logic is
covered by test_compliance_service.py, not re-tested here).
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import jwt
from fastapi.testclient import TestClient

from control_center.compliance.router import MANAGE_ALL_ORGS
from control_center.core import jwt_verify as jwt_verify_module
from control_center.main import app
from _fake_redis import FakeRedis

client = TestClient(app)
SECRET = "test-secret"

_REPORT_STUB = {
    "organization_id": 1,
    "organization_name": "KUMC Research",
    "from_date": "2026-08-01",
    "to_date": "2026-08-31",
    "generated_at": "2026-08-11T12:00:00+00:00",
    "generated_by": "admin@omnibioai.org",
    "summary": {"total_users": 2, "active_users": 1, "total_rag_queries": 3, "security_incidents": 0},
    "user_access": [],
    "rag_queries": [],
    "security_events": [],
    "truncated": False,
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


class HipaaReportEndpointTestCase(ComplianceRouterTestCase):
    def test_returns_report_body(self) -> None:
        r = client.get("/compliance/hipaa-report", params=self._params(), headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["organization_name"], "KUMC Research")

    def test_missing_required_params_returns_422(self) -> None:
        r = client.get("/compliance/hipaa-report", params={"from_date": "2026-08-01"}, headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.status_code, 422)

    def test_from_date_after_to_date_returns_400(self) -> None:
        params = self._params(from_date="2026-08-31", to_date="2026-08-01")
        r = client.get("/compliance/hipaa-report", params=params, headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.status_code, 400)

    def test_generated_by_uses_token_email_claim(self) -> None:
        headers = _auth(sub="1", email="alice@kumc.edu", permissions=[MANAGE_ALL_ORGS])
        r = client.get("/compliance/hipaa-report", params=self._params(), headers=headers)
        self.assertEqual(r.status_code, 200)
        _, kwargs = self.build_report_mock.call_args
        self.assertEqual(kwargs["generated_by"], "alice@kumc.edu")

    def test_generated_by_falls_back_to_sub_without_email_claim(self) -> None:
        headers = _auth(sub="42", permissions=[MANAGE_ALL_ORGS])
        r = client.get("/compliance/hipaa-report", params=self._params(), headers=headers)
        self.assertEqual(r.status_code, 200)
        _, kwargs = self.build_report_mock.call_args
        self.assertEqual(kwargs["generated_by"], "42")

    def test_second_request_hits_cache_not_build_report_again(self) -> None:
        headers = _auth(sub="1", permissions=[MANAGE_ALL_ORGS])
        r1 = client.get("/compliance/hipaa-report", params=self._params(), headers=headers)
        r2 = client.get("/compliance/hipaa-report", params=self._params(), headers=headers)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(self.build_report_mock.await_count, 1)

    def test_different_org_id_is_not_cached_together(self) -> None:
        headers = _auth(sub="1", permissions=[MANAGE_ALL_ORGS])
        client.get("/compliance/hipaa-report", params=self._params(org_id=1), headers=headers)
        client.get("/compliance/hipaa-report", params=self._params(org_id=2), headers=headers)
        self.assertEqual(self.build_report_mock.await_count, 2)


if __name__ == "__main__":
    unittest.main()
