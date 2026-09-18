"""
tests/test_core_auth.py

Unit tests for:
  - control_center.core.auth.require_permission

PR3D: require_admin's hardcoded "admin" in roles check was replaced by a
parameterized permission check against the JWT's `permissions` claim.
These tests cover authentication (unchanged, still delegated to
core.jwt_verify), authorization against a specific permission, and
isolation between the three permissions this PR introduces.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import jwt
from fastapi import HTTPException

from control_center.core import auth as auth_module
from control_center.core import jwt_verify as jwt_verify_module

SECRET = "test-secret"

PLATFORM_MANAGE_INFRA = "platform.manage_infra"
PLATFORM_MANAGE_CRON = "platform.manage_cron"
PLATFORM_MANAGE_CONTENT = "platform.manage_content"


def _token(**claims) -> str:
    """A JWT signed with the test SECRET, carrying the given claims."""
    return jwt.encode(claims, SECRET, algorithm="HS256")


class TestRequirePermissionAuthentication(unittest.TestCase):
    """Token verification is delegated to core.jwt_verify and is unchanged
    by PR3D -- these mirror the pre-PR3D require_admin authentication
    cases, now run against require_permission."""

    def setUp(self) -> None:
        patcher = patch.object(jwt_verify_module, "JWT_SECRET", SECRET)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.check = auth_module.require_permission(PLATFORM_MANAGE_INFRA)

    def test_missing_header_raises_401(self) -> None:
        """No Authorization header at all raises 401."""
        with self.assertRaises(HTTPException) as ctx:
            self.check(None)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_non_bearer_header_raises_401(self) -> None:
        """A non-Bearer auth scheme raises 401."""
        with self.assertRaises(HTTPException) as ctx:
            self.check("Basic abc123")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_malformed_token_raises_401(self) -> None:
        """A Bearer token that isn't a valid JWT raises 401."""
        with self.assertRaises(HTTPException) as ctx:
            self.check("Bearer not-a-real-token")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_invalid_signature_raises_401(self) -> None:
        """A token signed with the wrong secret raises 401."""
        token = jwt.encode(
            {"sub": "1", "permissions": [PLATFORM_MANAGE_INFRA]},
            "wrong-secret", algorithm="HS256",
        )
        with self.assertRaises(HTTPException) as ctx:
            self.check(f"Bearer {token}")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_expired_token_raises_401(self) -> None:
        """A token with a past `exp` claim raises 401."""
        import datetime
        token = jwt.encode(
            {
                "sub": "1",
                "permissions": [PLATFORM_MANAGE_INFRA],
                "exp": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1),
            },
            SECRET, algorithm="HS256",
        )
        with self.assertRaises(HTTPException) as ctx:
            self.check(f"Bearer {token}")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_bearer_prefix_case_insensitive(self) -> None:
        """A lowercase "bearer" prefix is accepted the same as "Bearer"."""
        token = _token(sub="1", permissions=[PLATFORM_MANAGE_INFRA])
        payload = self.check(f"bearer {token}")
        self.assertIn(PLATFORM_MANAGE_INFRA, payload["permissions"])


class TestRequirePermissionAuthorization(unittest.TestCase):
    """require_permission()'s per-permission authorization check against
    a validly-authenticated token."""

    def setUp(self) -> None:
        patcher = patch.object(jwt_verify_module, "JWT_SECRET", SECRET)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_valid_token_without_permission_raises_403(self) -> None:
        """A valid token with an empty permissions list raises 403."""
        check = auth_module.require_permission(PLATFORM_MANAGE_INFRA)
        token = _token(sub="1", permissions=[])
        with self.assertRaises(HTTPException) as ctx:
            check(f"Bearer {token}")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_valid_token_missing_permissions_claim_raises_403(self) -> None:
        """A valid token with no permissions claim at all raises 403."""
        check = auth_module.require_permission(PLATFORM_MANAGE_INFRA)
        token = _token(sub="1")
        with self.assertRaises(HTTPException) as ctx:
            check(f"Bearer {token}")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_valid_token_with_permission_returns_payload(self) -> None:
        """A token carrying the required permission returns the decoded
        payload, including the permissions list."""
        check = auth_module.require_permission(PLATFORM_MANAGE_INFRA)
        token = _token(sub="1", email="admin@omnibioai", permissions=[PLATFORM_MANAGE_INFRA])
        payload = check(f"Bearer {token}")
        self.assertEqual(payload["sub"], "1")
        self.assertIn(PLATFORM_MANAGE_INFRA, payload["permissions"])

    def test_admin_role_without_permission_raises_403(self) -> None:
        """A token that still carries the legacy "admin" role but was
        minted before the permission grant landed (or simply never had
        it) must not fall back to a role check -- proves PR3D left no
        role-string fallback path."""
        check = auth_module.require_permission(PLATFORM_MANAGE_INFRA)
        token = _token(sub="1", roles=["admin"], permissions=[])
        with self.assertRaises(HTTPException) as ctx:
            check(f"Bearer {token}")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_unrelated_permission_raises_403(self) -> None:
        """A token with a real but unrelated permission raises 403 for
        the required permission."""
        check = auth_module.require_permission(PLATFORM_MANAGE_INFRA)
        token = _token(sub="1", permissions=["manage_licenses"])
        with self.assertRaises(HTTPException) as ctx:
            check(f"Bearer {token}")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_unknown_permission_raises_403_never_fails_open(self) -> None:
        """A permission string that doesn't correspond to any real IAM
        grant must still be denied -- proves there's no wildcard/fail-open
        path for permissions IAM has never issued."""
        check = auth_module.require_permission(PLATFORM_MANAGE_INFRA)
        token = _token(sub="1", permissions=["fake.permission"])
        with self.assertRaises(HTTPException) as ctx:
            check(f"Bearer {token}")
        self.assertEqual(ctx.exception.status_code, 403)


class TestRequirePermissionIsolation(unittest.TestCase):
    """The three platform.* permissions introduced by PR3D must each be
    independently required -- holding one must not satisfy a check for
    another."""

    def setUp(self) -> None:
        patcher = patch.object(jwt_verify_module, "JWT_SECRET", SECRET)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_cron_permission_does_not_satisfy_content_check(self) -> None:
        """A token holding only platform.manage_cron is denied with 403 by a
        platform.manage_content check."""
        content_check = auth_module.require_permission(PLATFORM_MANAGE_CONTENT)
        token = _token(sub="1", permissions=[PLATFORM_MANAGE_CRON])
        with self.assertRaises(HTTPException) as ctx:
            content_check(f"Bearer {token}")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_content_permission_does_not_satisfy_infra_check(self) -> None:
        """A token holding only platform.manage_content is denied with 403 by a
        platform.manage_infra check."""
        infra_check = auth_module.require_permission(PLATFORM_MANAGE_INFRA)
        token = _token(sub="1", permissions=[PLATFORM_MANAGE_CONTENT])
        with self.assertRaises(HTTPException) as ctx:
            infra_check(f"Bearer {token}")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_infra_permission_does_not_satisfy_cron_check(self) -> None:
        """A token holding only platform.manage_infra is denied with 403 by a
        platform.manage_cron check."""
        cron_check = auth_module.require_permission(PLATFORM_MANAGE_CRON)
        token = _token(sub="1", permissions=[PLATFORM_MANAGE_INFRA])
        with self.assertRaises(HTTPException) as ctx:
            cron_check(f"Bearer {token}")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_all_three_permissions_together_satisfy_every_check(self) -> None:
        """A token holding all three platform permissions satisfies each of the three
        checks and returns a payload containing the checked permission."""
        token = _token(
            sub="1",
            roles=["admin"],
            permissions=[PLATFORM_MANAGE_INFRA, PLATFORM_MANAGE_CRON, PLATFORM_MANAGE_CONTENT],
        )
        for permission in (PLATFORM_MANAGE_INFRA, PLATFORM_MANAGE_CRON, PLATFORM_MANAGE_CONTENT):
            check = auth_module.require_permission(permission)
            payload = check(f"Bearer {token}")
            self.assertIn(permission, payload["permissions"])


if __name__ == "__main__":
    unittest.main()
