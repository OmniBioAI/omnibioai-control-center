"""
tests/test_jwt_key_rotation.py

Unit tests for:
  - control_center.core.jwt_verify.verify_token (HS256 key rotation)
  - control_center.core.jwt_verify._hs256_keys

JWT_SECRET_PREVIOUS is accepted for verification only, and only until
JWT_SECRET_PREVIOUS_UNTIL; an unset or empty value never becomes a key.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
import secrets
import unittest
from unittest.mock import MagicMock, patch

import jwt

from control_center.core import jwt_verify as jwt_verify_module
from control_center.core.jwt_verify import TokenInvalid, verify_token

CURRENT = "current-" + "c" * 40
PREVIOUS = "previous-" + "p" * 40
UNTIL = "2026-11-16T06:35:27Z"
_UNTIL_DT = datetime.datetime(2026, 11, 16, 6, 35, 27, tzinfo=datetime.timezone.utc)
BEFORE = _UNTIL_DT - datetime.timedelta(seconds=1)
AFTER = _UNTIL_DT + datetime.timedelta(seconds=1)


def _token(key: str, **claims) -> str:
    """An HS256 JWT signed with `key`, carrying sub=1 plus the given claims."""
    return jwt.encode({"sub": "1", **claims}, key, algorithm="HS256")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _empty_key_token() -> str:
    """An HS256 JWT whose HMAC key is the empty string, built by hand
    (PyJWT refuses to sign with an empty key)."""
    signing_input = (
        _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        + "."
        + _b64(json.dumps({"sub": "1"}).encode())
    )
    sig = hmac.new(b"", signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(sig)}"


class _RotationCase(unittest.TestCase):
    """Patches the key settings and the revocation store for each test."""

    def _set(self, current=CURRENT, previous=PREVIOUS, until=UNTIL) -> None:
        for name, value in (
            ("JWT_SECRET", current),
            ("JWT_SECRET_PREVIOUS", previous),
            ("JWT_SECRET_PREVIOUS_UNTIL", until),
        ):
            patcher = patch.object(jwt_verify_module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _now(self, now: datetime.datetime) -> None:
        real = jwt_verify_module._hs256_keys
        patcher = patch.object(
            jwt_verify_module, "_hs256_keys", lambda: real(now=now)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def setUp(self) -> None:
        blacklist = MagicMock()
        blacklist.exists.return_value = False
        patcher = patch.object(jwt_verify_module, "_blacklist", blacklist)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestKeyRotationVerify(_RotationCase):
    """verify_token() against the current and previous keys."""

    def test_current_key_valid(self) -> None:
        """A token signed with the current key verifies, before and after UNTIL."""
        self._set()
        real = jwt_verify_module._hs256_keys
        for now in (BEFORE, AFTER):
            with self.subTest(now=now), patch.object(
                jwt_verify_module, "_hs256_keys", lambda now=now: real(now=now)
            ):
                self.assertEqual(verify_token(_token(CURRENT))["sub"], "1")

    def test_previous_key_valid_before_until(self) -> None:
        """A token signed with the previous key verifies while UNTIL is in the future."""
        self._set()
        self._now(BEFORE)
        self.assertEqual(verify_token(_token(PREVIOUS))["sub"], "1")

    def test_previous_key_rejected_after_until(self) -> None:
        """Once UNTIL has passed, the previous key is ignored."""
        self._set()
        self._now(AFTER)
        with self.assertRaises(TokenInvalid):
            verify_token(_token(PREVIOUS))

    def test_previous_key_rejected_at_until(self) -> None:
        """UNTIL itself is already outside the window."""
        self._set()
        self._now(_UNTIL_DT)
        with self.assertRaises(TokenInvalid):
            verify_token(_token(PREVIOUS))

    def test_empty_or_unset_previous_key_rejected(self) -> None:
        """An empty or whitespace previous key is disabled; a token signed
        with the empty string is never accepted."""
        self._now(BEFORE)
        for previous in ("", "   "):
            with self.subTest(previous=repr(previous)):
                self._set(previous=previous)
                with self.assertRaises(TokenInvalid):
                    verify_token(_empty_key_token())
                with self.assertRaises(TokenInvalid):
                    verify_token(_token(PREVIOUS))

    def test_empty_current_key_never_used(self) -> None:
        """An empty JWT_SECRET is not a key: a token signed with "" is rejected."""
        self._set(current="", previous="")
        with self.assertRaises(TokenInvalid) as ctx:
            verify_token(_empty_key_token())
        self.assertIn("no HS256 verification key", str(ctx.exception))

    def test_random_key_rejected(self) -> None:
        """A token signed with an unrelated random key is rejected."""
        self._set()
        self._now(BEFORE)
        with self.assertRaises(TokenInvalid) as ctx:
            verify_token(_token(secrets.token_urlsafe(32)))
        self.assertIn("Signature verification failed", str(ctx.exception))

    def test_expired_token_signed_with_previous_key(self) -> None:
        """A previous-key token past its exp reports expiry, not a bad signature."""
        self._set()
        self._now(BEFORE)
        past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1)
        with self.assertRaises(TokenInvalid) as ctx:
            verify_token(_token(PREVIOUS, exp=past))
        self.assertEqual(str(ctx.exception), "expired")

    def test_wrong_audience_signed_with_previous_key(self) -> None:
        """A previous-key token with a wrong aud is rejected on the claim."""
        self._set()
        self._now(BEFORE)
        with self.assertRaises(TokenInvalid) as ctx:
            verify_token(_token(PREVIOUS, aud="someone-else"))
        self.assertIn("invalid token", str(ctx.exception))


class TestHs256Keys(_RotationCase):
    """_hs256_keys(): which keys are tried, in which order."""

    def test_order_is_current_then_previous(self) -> None:
        """The current key is always tried first."""
        self._set()
        self.assertEqual(jwt_verify_module._hs256_keys(now=BEFORE), [CURRENT, PREVIOUS])

    def test_previous_without_until_is_ignored(self) -> None:
        """A previous key with no UNTIL is disabled, so the overlap always ends."""
        self._set(until="")
        self.assertEqual(jwt_verify_module._hs256_keys(now=BEFORE), [CURRENT])

    def test_unparseable_or_naive_until_is_ignored(self) -> None:
        """An UNTIL that does not parse, or has no UTC offset, disables the previous key."""
        for until in ("not-a-date", "2026-11-16T06:35:27"):
            with self.subTest(until=until):
                self._set(until=until)
                self.assertEqual(jwt_verify_module._hs256_keys(now=BEFORE), [CURRENT])

    def test_offset_form_accepted(self) -> None:
        """+00:00 is accepted as well as Z."""
        self._set(until="2026-11-16T06:35:27+00:00")
        self.assertEqual(jwt_verify_module._hs256_keys(now=BEFORE), [CURRENT, PREVIOUS])

    def test_previous_equal_to_current_not_duplicated(self) -> None:
        """A previous key equal to the current key is not tried twice."""
        self._set(previous=CURRENT)
        self.assertEqual(jwt_verify_module._hs256_keys(now=BEFORE), [CURRENT])

    def test_default_now_is_wall_clock(self) -> None:
        """Without `now`, the wall clock decides (UNTIL far in the future here)."""
        self._set(until="2999-01-01T00:00:00Z")
        self.assertEqual(jwt_verify_module._hs256_keys(), [CURRENT, PREVIOUS])
