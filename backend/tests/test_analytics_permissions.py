"""
tests/test_analytics_permissions.py

Unit tests for control_center.analytics.permissions.require_analytics_scope.
Covers the task brief's own RBAC test matrix (Section 12): platform_admin
allowed, org_admin own-org allowed / other-org denied, team_admin
permitted-team allowed / unauthorized-team denied, regular user denied.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import jwt
from fastapi import HTTPException

from control_center.analytics import permissions
from control_center.core import jwt_verify as jwt_verify_module

SECRET = "test-secret"


def _token(**claims) -> str:
    return jwt.encode(claims, SECRET, algorithm="HS256")


class RequireAnalyticsScopeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.object(jwt_verify_module, "JWT_SECRET", SECRET)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _call(self, token: str, org_id=None, team_id=None):
        return permissions.require_analytics_scope(
            authorization=f"Bearer {token}", org_id=org_id, team_id=team_id,
        )


class AuthenticationTestCase(RequireAnalyticsScopeTestCase):
    def test_missing_header_raises_401(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            permissions.require_analytics_scope(authorization=None)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_non_bearer_header_raises_401(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            permissions.require_analytics_scope(authorization="Basic abc123")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_invalid_token_raises_401(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            permissions.require_analytics_scope(authorization="Bearer not-a-real-token")
        self.assertEqual(ctx.exception.status_code, 401)


class PlatformAdminTestCase(RequireAnalyticsScopeTestCase):
    def test_platform_admin_allowed_with_no_org_id_resolves_platform_wide(self) -> None:
        token = _token(sub="1", permissions=[permissions.MANAGE_ALL_ORGS])
        scope = self._call(token)
        self.assertTrue(scope.is_platform_admin)
        self.assertIsNone(scope.org_id)

    def test_platform_admin_can_request_any_org_id(self) -> None:
        token = _token(sub="1", permissions=[permissions.MANAGE_ALL_ORGS])
        scope = self._call(token, org_id=99, team_id=7)
        self.assertEqual(scope.org_id, 99)
        self.assertEqual(scope.team_id, 7)


class OrgAdminTestCase(RequireAnalyticsScopeTestCase):
    def test_org_admin_own_org_allowed(self) -> None:
        token = _token(sub="1", permissions=[], org_id=5, org_role=["org_admin"])
        scope = self._call(token, org_id=5)
        self.assertFalse(scope.is_platform_admin)
        self.assertEqual(scope.org_id, 5)

    def test_org_admin_no_org_id_param_resolves_to_own_org(self) -> None:
        token = _token(sub="1", permissions=[], org_id=5, org_role=["org_admin"])
        scope = self._call(token)
        self.assertEqual(scope.org_id, 5)

    def test_org_admin_other_org_denied(self) -> None:
        token = _token(sub="1", permissions=[], org_id=5, org_role=["org_admin"])
        with self.assertRaises(HTTPException) as ctx:
            self._call(token, org_id=6)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_org_admin_without_org_id_claim_falls_through_to_denied(self) -> None:
        token = _token(sub="1", permissions=[], org_id=None, org_role=["org_admin"])
        with self.assertRaises(HTTPException) as ctx:
            self._call(token)
        self.assertEqual(ctx.exception.status_code, 403)


class TeamAdminTestCase(RequireAnalyticsScopeTestCase):
    def test_team_admin_permitted_team_allowed(self) -> None:
        token = _token(sub="1", permissions=[], org_id=5, org_role=[], team_id=10, team_role="admin")
        scope = self._call(token, org_id=5, team_id=10)
        self.assertEqual(scope.org_id, 5)
        self.assertEqual(scope.team_id, 10)

    def test_team_admin_no_params_resolves_to_own_org_and_team(self) -> None:
        token = _token(sub="1", permissions=[], org_id=5, org_role=[], team_id=10, team_role="admin")
        scope = self._call(token)
        self.assertEqual(scope.org_id, 5)
        self.assertEqual(scope.team_id, 10)

    def test_team_admin_unauthorized_team_denied(self) -> None:
        token = _token(sub="1", permissions=[], org_id=5, org_role=[], team_id=10, team_role="admin")
        with self.assertRaises(HTTPException) as ctx:
            self._call(token, org_id=5, team_id=11)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_team_admin_unauthorized_org_denied(self) -> None:
        token = _token(sub="1", permissions=[], org_id=5, org_role=[], team_id=10, team_role="admin")
        with self.assertRaises(HTTPException) as ctx:
            self._call(token, org_id=6)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_non_admin_team_role_denied(self) -> None:
        token = _token(sub="1", permissions=[], org_id=5, org_role=[], team_id=10, team_role="member")
        with self.assertRaises(HTTPException) as ctx:
            self._call(token)
        self.assertEqual(ctx.exception.status_code, 403)


class RegularUserTestCase(RequireAnalyticsScopeTestCase):
    def test_regular_user_denied(self) -> None:
        token = _token(sub="1", permissions=[], org_id=5, org_role=["member"], team_id=None, team_role=None)
        with self.assertRaises(HTTPException) as ctx:
            self._call(token)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_no_org_membership_at_all_denied(self) -> None:
        token = _token(sub="1", permissions=[])
        with self.assertRaises(HTTPException) as ctx:
            self._call(token)
        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
