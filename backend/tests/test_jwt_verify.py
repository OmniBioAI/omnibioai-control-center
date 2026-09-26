"""
tests/test_jwt_verify.py

Unit tests for:
  - control_center.core.jwt_verify.verify_token

SSO Phase 2 PR3: the shared local JWT verifier (signature, expiry, token
type, required claims, Redis jti-blacklist revocation) core.auth.py::
require_admin now delegates to.

SSO Phase 2 PR16: adds coverage for the RS256/JWKS verification path
added alongside the existing HS256 path.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""
from __future__ import annotations

import datetime
import unittest
from unittest.mock import MagicMock, patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWKClient
from jwt.algorithms import RSAAlgorithm
from redis.exceptions import AuthenticationError, ResponseError

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
    """A JWT signed with the test SECRET (HS256), carrying the given claims."""
    return jwt.encode(claims, SECRET, algorithm="HS256")


def _rs256_token(private_key, kid, **claims) -> str:
    """A JWT signed with `private_key` (RS256), carrying the given kid
    header and claims."""
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})


def _jwk(public_key, kid: str) -> dict:
    """A JWKS "keys" entry for `public_key` under the given kid."""
    jwk = RSAAlgorithm.to_jwk(public_key, as_dict=True)
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return jwk


class TestVerifyToken(unittest.TestCase):
    """verify_token()'s HS256 and RS256/JWKS verification paths:
    signature/expiry/claim checks, Redis jti-blacklist revocation, and
    the PR12 iss/aud checks -- all fail closed, never silently accepting."""

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
        """A well-formed, correctly-signed access token verifies and
        returns its claims."""
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
        """None or an empty string both raise TokenInvalid."""
        with self.assertRaises(TokenInvalid):
            verify_token(None)
        with self.assertRaises(TokenInvalid):
            verify_token("")

    def test_invalid_signature_raises(self) -> None:
        """A token signed with the wrong secret raises TokenInvalid."""
        token = jwt.encode({"sub": "1"}, "wrong-secret", algorithm="HS256")
        with self.assertRaises(TokenInvalid):
            verify_token(token)

    def test_malformed_token_raises(self) -> None:
        """A non-JWT string raises TokenInvalid."""
        with self.assertRaises(TokenInvalid):
            verify_token("not-a-real-token")

    def test_expired_token_raises(self) -> None:
        """A token with a past `exp` claim raises TokenInvalid."""
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
        """A token missing the required "sub" claim raises TokenInvalid."""
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
        """Every other non-access token type (oauth_state, sso_state,
        oauth_link) is also rejected."""
        for bad_type in ("oauth_state", "sso_state", "oauth_link"):
            token = _token(sub="1", type=bad_type)
            with self.assertRaises(TokenInvalid):
                verify_token(token)

    # -- revocation (Redis jti blacklist) -------------------------------

    def test_blacklisted_jti_raises(self) -> None:
        """A token whose jti is present in the Redis blacklist raises
        TokenInvalid, and the correct blacklist key is checked."""
        self.mock_blacklist.exists.return_value = True
        token = _token(sub="1", jti="revoked-jti-123")
        with self.assertRaises(TokenInvalid):
            verify_token(token)
        self.mock_blacklist.exists.assert_called_once_with(
            "blacklist:jti:revoked-jti-123"
        )

    def test_non_blacklisted_jti_succeeds(self) -> None:
        """A jti that is not blacklisted still verifies normally."""
        self.mock_blacklist.exists.return_value = False
        token = _token(sub="1", jti="fine-jti-456")
        payload = verify_token(token)
        self.assertEqual(payload["sub"], "1")

    def test_token_without_jti_skips_blacklist_check(self) -> None:
        """A token with no jti claim at all never calls the blacklist
        check -- there's nothing to check against."""
        token = _token(sub="1")  # no jti claim at all
        payload = verify_token(token)
        self.assertEqual(payload["sub"], "1")
        self.mock_blacklist.exists.assert_not_called()

    def test_blacklist_redis_error_fails_closed(self) -> None:
        """A Redis outage must never make a revoked token usable."""
        self.mock_blacklist.exists.side_effect = Exception("redis down")
        token = _token(sub="1", jti="some-jti")
        with self.assertRaises(TokenInvalid) as exc:
            verify_token(token)
        self.assertIn("revocation state unavailable", str(exc.exception))

    def test_blacklist_authentication_and_acl_errors_fail_closed(self) -> None:
        for redis_error in (AuthenticationError("wrongpass"), ResponseError("NOPERM")):
            self.mock_blacklist.exists.side_effect = redis_error
            token = _token(sub="1", jti="security-state")
            with self.assertRaises(TokenInvalid) as exc:
                verify_token(token)
            self.assertIn("revocation state unavailable", str(exc.exception))
            self.mock_blacklist.exists.side_effect = None

    # -- RS256 / JWKS (PR16) -------------------------------------------

    def test_valid_rs256_token_succeeds(self) -> None:
        """A well-formed, correctly-signed RS256 token with a matching
        kid verifies via JWKS lookup."""
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
        """An RS256 token with no "kid" header at all raises TokenInvalid."""
        token = jwt.encode({"sub": "1"}, _PRIVATE_KEY, algorithm="RS256")
        with self.assertRaises(TokenInvalid):
            verify_token(token)

    def test_expired_rs256_token_raises(self) -> None:
        """An expired RS256 token raises TokenInvalid even with a
        matching, valid JWKS key."""
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

    # -- PR12: iss/aud -------------------------------------------------

    def test_token_with_matching_iss_and_aud_succeeds(self) -> None:
        """A token whose iss/aud claims match the configured values verifies."""
        token = _token(
            sub="1",
            iss=jwt_verify_module.JWT_ISSUER,
            aud=jwt_verify_module.JWT_AUDIENCE,
        )
        payload = verify_token(token)
        self.assertEqual(payload["sub"], "1")

    def test_token_missing_iss_and_aud_entirely_still_succeeds(self) -> None:
        """Migration-window requirement: a pre-PR12 (or synthetic test)
        token has neither claim -- every other test in this file relies on
        this already, this just makes it explicit."""
        token = _token(sub="1")
        payload = verify_token(token)
        self.assertEqual(payload["sub"], "1")

    def test_token_with_wrong_audience_raises(self) -> None:
        """A token with a mismatched aud claim (when an iss/aud check
        is triggered) raises TokenInvalid."""
        token = _token(sub="1", aud="some-other-service")
        with self.assertRaises(TokenInvalid):
            verify_token(token)

    def test_token_with_wrong_issuer_raises(self) -> None:
        """A token with a mismatched iss claim raises TokenInvalid."""
        token = _token(sub="1", iss="some-other-service")
        with self.assertRaises(TokenInvalid):
            verify_token(token)

    def test_rs256_token_with_matching_iss_and_aud_succeeds(self) -> None:
        """The iss/aud check applies equally on the RS256 path."""
        self._install_jwks({"keys": [_jwk(_PUBLIC_KEY, KID)]})
        token = _rs256_token(
            _PRIVATE_KEY,
            KID,
            sub="1",
            iss=jwt_verify_module.JWT_ISSUER,
            aud=jwt_verify_module.JWT_AUDIENCE,
        )
        payload = verify_token(token)
        self.assertEqual(payload["sub"], "1")

    def test_rs256_token_with_wrong_audience_raises(self) -> None:
        """The audience check also rejects a mismatched aud on the RS256 path."""
        self._install_jwks({"keys": [_jwk(_PUBLIC_KEY, KID)]})
        token = _rs256_token(_PRIVATE_KEY, KID, sub="1", aud="some-other-service")
        with self.assertRaises(TokenInvalid):
            verify_token(token)

    def test_unverified_claims_peek_failure_falls_back_to_no_claim_checks(self) -> None:
        """_migration_aware_claims_kwargs peeks at the unverified payload
        purely to decide whether to ask PyJWT to enforce aud/iss -- if that
        peek itself fails (e.g. a payload segment that isn't valid JSON),
        it must fall back to no claim-enforcement kwargs at all rather than
        raising, leaving the *real* signature-verified decode below to be
        the one that ultimately rejects the token."""

        def b64url(data: bytes) -> str:
            import base64

            return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

        header = b64url(b'{"alg": "HS256", "typ": "JWT"}')
        bad_payload = b64url(b"not-valid-json-at-all")
        token = f"{header}.{bad_payload}.sig"

        with self.assertRaises(TokenInvalid):
            verify_token(token)


if __name__ == "__main__":
    unittest.main()
