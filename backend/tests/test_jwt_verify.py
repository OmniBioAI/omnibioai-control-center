"""
tests/test_jwt_verify.py

Unit tests for:
  - control_center.core.jwt_verify.verify_token

SSO Phase 2 PR3: the shared local JWT verifier (signature, expiry, token
type, required claims, Redis jti-blacklist revocation) core.auth.py::
require_admin now delegates to.

SSO Phase 2 PR16: adds coverage for the RS256/JWKS verification path
added alongside the existing HS256 path.
"""
from __future__ import annotations

import datetime
import unittest
from unittest.mock import MagicMock, patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWKClient
from jwt.algorithms import RSAAlgorithm

from control_center.core import jwt_verify as jwt_verify_module
from control_center.core.jwt_verify import TokenInvalid, verify_token

SECRET = "test-secret"

KID = "test-kid-1"
_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()

OTHER_KID = "test-kid-2"
_OTHER_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_PUBLIC_KEY = _OTHER_PRIVATE_KEY.public_key()


def _token(**claims) -> str:
    return jwt.encode(claims, SECRET, algorithm="HS256")


def _rs256_token(private_key, kid, **claims) -> str:
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})


def _jwk(public_key, kid: str) -> dict:
    jwk = RSAAlgorithm.to_jwk(public_key, as_dict=True)
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return jwk


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

        # Every test starts with no cached JWKS client -- RS256 tests
        # install their own fake via _install_jwks(); tests that never
        # touch RS256 never trigger a real network fetch.
        jwks_patcher = patch.object(jwt_verify_module, "_jwks_client", None)
        jwks_patcher.start()
        self.addCleanup(jwks_patcher.stop)

    def _install_jwks(self, *jwks_responses: dict) -> MagicMock:
        """Wires a real PyJWKClient (so get_signing_key's actual
        match/refresh-on-miss logic runs) whose network fetch is replaced
        by a canned sequence of JWKS responses -- one per expected
        fetch_data() call."""
        client = PyJWKClient(jwt_verify_module.JWKS_URL)
        fetch = MagicMock(side_effect=list(jwks_responses))
        client.fetch_data = fetch
        jwt_verify_module._jwks_client = client
        return fetch

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

    # -- RS256 / JWKS (PR16) -------------------------------------------

    def test_valid_rs256_token_succeeds(self) -> None:
        self._install_jwks({"keys": [_jwk(_PUBLIC_KEY, KID)]})
        token = _rs256_token(_PRIVATE_KEY, KID, sub="1", roles=["admin"], type="access")
        payload = verify_token(token)
        self.assertEqual(payload["sub"], "1")
        self.assertEqual(payload["roles"], ["admin"])

    def test_invalid_rs256_signature_raises(self) -> None:
        """Token claims kid=KID in its header but was actually signed by a
        different key -- JWKS lookup resolves KID's real public key, so
        the signature check must fail rather than trusting the header."""
        self._install_jwks({"keys": [_jwk(_PUBLIC_KEY, KID)]})
        forged = _rs256_token(_OTHER_PRIVATE_KEY, KID, sub="1")
        with self.assertRaises(TokenInvalid):
            verify_token(forged)

    def test_unknown_kid_rejected(self) -> None:
        """Neither the initial fetch nor the refresh-on-miss fetch ever
        contains the token's kid -- must fail closed, not fall back to
        any other verification path."""
        fetch = self._install_jwks(
            {"keys": [_jwk(_PUBLIC_KEY, KID)]},
            {"keys": [_jwk(_PUBLIC_KEY, KID)]},
        )
        token = _rs256_token(_OTHER_PRIVATE_KEY, "no-such-kid", sub="1")
        with self.assertRaises(TokenInvalid):
            verify_token(token)
        self.assertEqual(fetch.call_count, 2)

    def test_jwks_refresh_finds_rotated_key(self) -> None:
        """Simulates key rotation: the token's kid isn't in the JWKS
        response cached at the time verification starts, but is present
        once PyJWKClient refetches after the initial miss."""
        fetch = self._install_jwks(
            {"keys": [_jwk(_PUBLIC_KEY, KID)]},
            {"keys": [_jwk(_PUBLIC_KEY, KID), _jwk(_OTHER_PUBLIC_KEY, OTHER_KID)]},
        )
        token = _rs256_token(_OTHER_PRIVATE_KEY, OTHER_KID, sub="1")
        payload = verify_token(token)
        self.assertEqual(payload["sub"], "1")
        self.assertEqual(fetch.call_count, 2)

    def test_jwks_fetch_failure_fails_closed(self) -> None:
        """A network/timeout error while fetching the JWKS must reject the
        token, never fall back to an unverified accept."""
        client = PyJWKClient(jwt_verify_module.JWKS_URL)
        client.fetch_data = MagicMock(side_effect=TimeoutError("jwks unreachable"))
        jwt_verify_module._jwks_client = client
        token = _rs256_token(_PRIVATE_KEY, KID, sub="1")
        with self.assertRaises(TokenInvalid):
            verify_token(token)

    def test_unsigned_token_rejected(self) -> None:
        """alg=none tokens must never be accepted, regardless of JWKS or
        HS256 secret state."""
        token = jwt.encode({"sub": "1"}, key=None, algorithm="none")
        with self.assertRaises(TokenInvalid):
            verify_token(token)

    def test_rs256_token_missing_kid_raises(self) -> None:
        token = jwt.encode({"sub": "1"}, _PRIVATE_KEY, algorithm="RS256")
        with self.assertRaises(TokenInvalid):
            verify_token(token)

    def test_expired_rs256_token_raises(self) -> None:
        self._install_jwks({"keys": [_jwk(_PUBLIC_KEY, KID)]})
        token = _rs256_token(
            _PRIVATE_KEY,
            KID,
            sub="1",
            exp=datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(minutes=1),
        )
        with self.assertRaises(TokenInvalid):
            verify_token(token)

    def test_get_jwks_client_lazily_builds_real_client(self) -> None:
        """_jwks_client starts as None (setUp) -- the first RS256
        verification must build a real PyJWKClient pointed at JWKS_URL,
        not require a test to have pre-installed one."""
        client = jwt_verify_module._get_jwks_client()
        self.assertIsInstance(client, PyJWKClient)
        self.assertEqual(client.uri, jwt_verify_module.JWKS_URL)
        self.assertIs(jwt_verify_module._get_jwks_client(), client)

    def test_hs256_token_unaffected_by_rs256_path(self) -> None:
        """Old, already-issued HS256 tokens must keep validating exactly
        as before even with a JWKS client installed -- alg dispatch must
        never route an HS256 token through the RS256/JWKS path."""
        self._install_jwks({"keys": [_jwk(_PUBLIC_KEY, KID)]})
        token = _token(sub="1", roles=["admin"], type="access")
        payload = verify_token(token)
        self.assertEqual(payload["sub"], "1")


if __name__ == "__main__":
    unittest.main()
