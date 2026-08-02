"""
tests/test_jwt_verify.py

Unit tests for:
  - control_center.core.jwt_verify.verify_token

SSO Phase 2 PR3: the shared local JWT verifier (signature, expiry, token
type, required claims, Redis jti-blacklist revocation) core.auth.py::
require_admin now delegates to.
"""
from __future__ import annotations

import datetime
import unittest
from unittest.mock import MagicMock, patch

import jwt

from control_center.core import jwt_verify as jwt_verify_module
from control_center.core.jwt_verify import TokenInvalid, verify_token

SECRET = "test-secret"


def _token(**claims) -> str:
    return jwt.encode(claims, SECRET, algorithm="HS256")


class TestVerifyToken(unittest.TestCase):

    def setUp(self) -> None:
        secret_patcher = patch.object(jwt_verify_module, "JWT_SECRET", SECRET)
        secret_patcher.start()
        self.addCleanup(secret_patcher.stop)

        self.mock_blacklist = MagicMock()
        self.mock_blacklist.exists.return_value = False
        blacklist_patcher = patch.object(
            jwt_verify_module, "_blacklist", self.mock_blacklist
        )
        blacklist_patcher.start()
        self.addCleanup(blacklist_patcher.stop)

    # -- success path ------------------------------------------------

    def test_valid_token_succeeds(self) -> None:
        token = _token(sub="1", roles=["admin"], type="access")
        payload = verify_token(token)
        self.assertEqual(payload["sub"], "1")
        self.assertEqual(payload["roles"], ["admin"])

    def test_valid_token_without_type_claim_succeeds(self) -> None:
        """Every pre-PR3 test fixture in this repo omits `type` entirely
        -- must keep working unmodified."""
        token = _token(sub="1")
        payload = verify_token(token)
        self.assertEqual(payload["sub"], "1")

    # -- failure paths -------------------------------------------------

    def test_missing_token_raises(self) -> None:
        with self.assertRaises(TokenInvalid):
            verify_token(None)
        with self.assertRaises(TokenInvalid):
            verify_token("")

    def test_invalid_signature_raises(self) -> None:
        token = jwt.encode({"sub": "1"}, "wrong-secret", algorithm="HS256")
        with self.assertRaises(TokenInvalid):
            verify_token(token)

    def test_malformed_token_raises(self) -> None:
        with self.assertRaises(TokenInvalid):
            verify_token("not-a-real-token")

    def test_expired_token_raises(self) -> None:
        token = jwt.encode(
            {
                "sub": "1",
                "exp": datetime.datetime.now(datetime.timezone.utc)
                - datetime.timedelta(minutes=1),
            },
            SECRET,
            algorithm="HS256",
        )
        with self.assertRaises(TokenInvalid):
            verify_token(token)

    def test_missing_sub_claim_raises(self) -> None:
        token = _token(email="x@y.com")
        with self.assertRaises(TokenInvalid):
            verify_token(token)

    def test_wrong_token_type_raises(self) -> None:
        """omnibioai-auth signs refresh tokens with the SAME claim set as
        access tokens (build_user_claims) -- differing only in `type` and
        TTL (7 days vs 15 minutes). Before this check, a leaked refresh
        token granted the same access as a stolen access token, for up to
        7 days instead of 15 minutes."""
        token = _token(sub="1", roles=["admin"], type="refresh")
        with self.assertRaises(TokenInvalid):
            verify_token(token)

    def test_other_token_types_also_rejected(self) -> None:
        for bad_type in ("oauth_state", "sso_state", "oauth_link"):
            token = _token(sub="1", type=bad_type)
            with self.assertRaises(TokenInvalid):
                verify_token(token)

    # -- revocation (Redis jti blacklist) -------------------------------

    def test_blacklisted_jti_raises(self) -> None:
        self.mock_blacklist.exists.return_value = True
        token = _token(sub="1", jti="revoked-jti-123")
        with self.assertRaises(TokenInvalid):
            verify_token(token)
        self.mock_blacklist.exists.assert_called_once_with(
            "blacklist:jti:revoked-jti-123"
        )

    def test_non_blacklisted_jti_succeeds(self) -> None:
        self.mock_blacklist.exists.return_value = False
        token = _token(sub="1", jti="fine-jti-456")
        payload = verify_token(token)
        self.assertEqual(payload["sub"], "1")

    def test_token_without_jti_skips_blacklist_check(self) -> None:
        token = _token(sub="1")  # no jti claim at all
        payload = verify_token(token)
        self.assertEqual(payload["sub"], "1")
        self.mock_blacklist.exists.assert_not_called()

    def test_blacklist_redis_error_fails_open(self) -> None:
        """Matches omnibioai-auth/app/core/token_revocation.py's own
        documented tradeoff: a Redis outage must not 401 every request in
        this service either."""
        self.mock_blacklist.exists.side_effect = Exception("redis down")
        token = _token(sub="1", jti="some-jti")
        payload = verify_token(token)  # must not raise
        self.assertEqual(payload["sub"], "1")


if __name__ == "__main__":
    unittest.main()
