"""
tests/test_core_auth.py

Unit tests for:
  - control_center.core.auth.require_admin
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import jwt
from fastapi import HTTPException

from control_center.core import auth as auth_module
from control_center.core import jwt_verify as jwt_verify_module

SECRET = "test-secret"


def _token(**claims) -> str:
    return jwt.encode(claims, SECRET, algorithm="HS256")


class TestRequireAdmin(unittest.TestCase):

    def setUp(self) -> None:
        # SSO Phase 2 PR3: decoding now happens in core.jwt_verify, not
        # core.auth -- auth_module no longer has its own JWT_SECRET.
        patcher = patch.object(jwt_verify_module, "JWT_SECRET", SECRET)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_missing_header_raises_401(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            auth_module.require_admin(None)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_non_bearer_header_raises_401(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            auth_module.require_admin("Basic abc123")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_invalid_token_raises_401(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            auth_module.require_admin("Bearer not-a-real-token")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_expired_token_raises_401(self) -> None:
        import datetime
        token = jwt.encode(
            {"sub": "1", "roles": ["admin"],
             "exp": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1)},
            SECRET, algorithm="HS256",
        )
        with self.assertRaises(HTTPException) as ctx:
            auth_module.require_admin(f"Bearer {token}")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_valid_token_without_admin_role_raises_403(self) -> None:
        token = _token(sub="1", roles=["user"])
        with self.assertRaises(HTTPException) as ctx:
            auth_module.require_admin(f"Bearer {token}")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_valid_token_missing_roles_claim_raises_403(self) -> None:
        token = _token(sub="1")
        with self.assertRaises(HTTPException) as ctx:
            auth_module.require_admin(f"Bearer {token}")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_valid_admin_token_returns_payload(self) -> None:
        token = _token(sub="1", email="admin@omnibioai", roles=["admin"], permissions=["manage_roles"])
        payload = auth_module.require_admin(f"Bearer {token}")
        self.assertEqual(payload["sub"], "1")
        self.assertIn("admin", payload["roles"])

    def test_bearer_prefix_case_insensitive(self) -> None:
        token = _token(sub="1", roles=["admin"])
        payload = auth_module.require_admin(f"bearer {token}")
        self.assertIn("admin", payload["roles"])


if __name__ == "__main__":
    unittest.main()
