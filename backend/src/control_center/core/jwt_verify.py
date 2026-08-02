"""SSO Phase 2 PR3: the single place in this repo that decodes and fully
verifies an omnibioai-auth-issued JWT -- signature, expiry, token type,
required claims, and Redis jti-blacklist revocation state.

core/auth.py::require_admin previously did its own partial jwt.decode()
(signature + exp only, via PyJWT's defaults) with no revocation check at
all -- a logged-out or suspended admin's still-unexpired access token
stayed valid against this service until natural expiry. It now delegates
here.

Not shared across repos: omnibioai-security-audit has its own, separately
maintained but structurally identical module (audit/jwt_verify.py). Two
existing candidate shared packages (omnibioai-iam-client,
omnibioai-security-sdk) were inspected first and found unsuitable --
neither is imported by any live service today, and neither implements
local-decode-plus-jti-blacklist verification (one does remote-validate-
with-cache, the other does bare decode with no revocation check at all).
See this PR's report for detail. A future PR may extract a true shared
package once this pattern has proven itself in both repos.
"""
from __future__ import annotations

import os
from typing import Any

import jwt
import redis

JWT_SECRET = os.environ.get("JWT_SECRET", "change-me")

# Same Redis instance and key convention as omnibioai-auth's own
# token_revocation.py::_blacklist ("blacklist:jti:{jti}", checked via
# .exists(), fail-open on Redis errors). Defaults to the in-network
# hostname docker-compose-release.yml's other services already resolve
# (redis://redis:6379) -- this repo's compose block does not wire
# REDIS_URL explicitly yet (out of this PR's scope; a natural follow-up,
# same pattern as SSO PR1/PR2's JWT_SECRET wiring).
_REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
_blacklist = redis.from_url(_REDIS_URL, decode_responses=True)


class TokenInvalid(Exception):
    """Raised by verify_token() for any invalid, expired, wrong-type,
    missing-required-claim, or revoked token. Callers decide how to
    surface this (HTTPException, ...) -- this module only verifies, it
    never decides what an invalid token means to its caller."""


def verify_token(token: str | None) -> dict[str, Any]:
    """Decodes and verifies `token`. Returns the decoded payload on
    success; raises TokenInvalid on any failure."""
    if not token:
        raise TokenInvalid("missing token")

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise TokenInvalid("expired")
    except jwt.InvalidTokenError as e:
        raise TokenInvalid(f"invalid token: {e}")

    # Permissive by design: omnibioai-auth's refresh tokens carry the same
    # claim set as access tokens (build_user_claims), differing only in
    # `type` and TTL (7 days vs 15 minutes) -- without this check, a
    # leaked refresh token grants the same access as an access token, for
    # up to 7 days instead of 15 minutes. Only reject a *known-wrong*
    # type; a token with no `type` claim at all (every pre-existing test
    # fixture in this repo) still passes, so this closes the real gap
    # without requiring a claim that wasn't part of the original contract
    # these callers were built against.
    token_type = payload.get("type")
    if token_type is not None and token_type != "access":
        raise TokenInvalid(f"wrong token type: {token_type!r}")

    if not payload.get("sub"):
        raise TokenInvalid("missing required claim: sub")

    jti = payload.get("jti")
    if jti:
        try:
            revoked = bool(_blacklist.exists(f"blacklist:jti:{jti}"))
        except Exception:
            # Fail open on Redis specifically -- matches
            # omnibioai-auth/app/core/token_revocation.py's own documented
            # "never block on a Redis blip" philosophy for this exact
            # blacklist.
            revoked = False
        if revoked:
            raise TokenInvalid("revoked")

    return payload
