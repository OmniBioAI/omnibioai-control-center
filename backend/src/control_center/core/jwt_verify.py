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

SSO Phase 2 PR16: adds RS256/JWKS verification alongside the existing
HS256 shared-secret path, dispatched by the token's own `alg` header --
the same "verify by declared alg, not by config" approach
omnibioai-auth/app/core/jwt.py::decode_token already uses so a token
issued today (HS256) and one issued after a future RS256 cutover both
keep validating here without a coordinated flag flip. JWT_ALGORITHM=RS256
is NOT enabled anywhere yet -- this PR only prepares this service to
verify RS256 tokens once that switch is made in a later, separate change.
"""
from __future__ import annotations

import datetime
import os
from typing import Any

import jwt
import redis
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError

JWT_SECRET = os.environ.get("JWT_SECRET", "change-me")

# Key rotation: an optional previous HS256 key, accepted for verification
# only until JWT_SECRET_PREVIOUS_UNTIL (ISO-8601, UTC offset required, e.g.
# 2026-11-16T06:35:27Z). Nothing in this service ever signs with it. An
# unset, empty or whitespace-only value never becomes a key, and a previous
# key without a parseable, timezone-aware UNTIL is ignored, so an overlap
# window always ends. Read at call time (see _hs256_keys) so tests can patch
# these module attributes the same way they already patch JWT_SECRET.
JWT_SECRET_PREVIOUS = os.environ.get("JWT_SECRET_PREVIOUS", "")
JWT_SECRET_PREVIOUS_UNTIL = os.environ.get("JWT_SECRET_PREVIOUS_UNTIL", "")

# PR12: omnibioai-auth now stamps every token with iss=omnibioai-auth,
# aud=omnibioai-platform (app/core/jwt.py::_sign there). PyJWT's `aud`
# handling is stricter than jose's in *both* directions: passing
# `audience=` when the token has no `aud` claim raises
# MissingRequiredClaimError, but *not* passing it when the token does have
# one raises InvalidAudienceError -- so which kwargs to pass has to be
# decided per-token (see _migration_aware_claims_kwargs below), not fixed,
# to keep verifying pre-PR12/synthetic tokens that carry neither claim.
JWT_ISSUER = os.environ.get("JWT_ISSUER", "omnibioai-auth")
JWT_AUDIENCE = os.environ.get("JWT_AUDIENCE", "omnibioai-platform")

# omnibioai-auth's JWKS endpoint (app/api/routes_jwks.py) -- publishes the
# public half of whatever key app/core/rsa_keys.py loaded/generated, keyed
# by `kid`. Only ever consulted for a token whose header already declares
# alg=RS256; an HS256 token never triggers a fetch.
JWKS_URL = os.environ.get(
    "JWKS_URL", "https://auth.omnibioai.org/.well-known/jwks.json"
)
JWKS_TIMEOUT_SECONDS = int(os.environ.get("JWKS_TIMEOUT_SECONDS", "5"))
# How long a fetched key set is trusted before the next RS256 verification
# re-fetches it. Independent of the "unknown kid -> refresh immediately"
# path in _decode(), which ignores this TTL entirely.
JWKS_CACHE_TTL_SECONDS = int(os.environ.get("JWKS_CACHE_TTL_SECONDS", "300"))

# Same Redis instance and key convention as omnibioai-auth's own
# token_revocation.py::_blacklist ("blacklist:jti:{jti}", checked via
# .exists(), fail-closed on Redis errors). Defaults to the in-network
# hostname docker-compose-release.yml's other services already resolve
# (redis://redis:6379) -- this repo's compose block does not wire
# REDIS_URL explicitly yet (out of this PR's scope; a natural follow-up,
# same pattern as SSO PR1/PR2's JWT_SECRET wiring).
_REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
_blacklist = redis.from_url(_REDIS_URL, decode_responses=True)

# Lazy singleton: importing this module must never make a network call --
# only the first RS256 token that actually arrives pays for the initial
# JWKS fetch. PyJWKClient itself caches the fetched key set for
# JWKS_CACHE_TTL_SECONDS and transparently refetches once if a requested
# kid isn't in the cached set (see its get_signing_key()), which is the
# "refresh cache on unknown kid" behavior this PR requires.
_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(
            JWKS_URL, timeout=JWKS_TIMEOUT_SECONDS, lifespan=JWKS_CACHE_TTL_SECONDS
        )
    return _jwks_client


class TokenInvalid(Exception):
    """Raised by verify_token() for any invalid, expired, wrong-type,
    missing-required-claim, or revoked token. Callers decide how to
    surface this (HTTPException, ...) -- this module only verifies, it
    never decides what an invalid token means to its caller."""


def _previous_key_until(raw: str) -> datetime.datetime | None:
    """JWT_SECRET_PREVIOUS_UNTIL as an aware datetime, or None when it is
    unset, unparseable or has no UTC offset (each of which disables the
    previous key)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        until = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if until.tzinfo is None:
        return None
    return until


def _hs256_keys(now: datetime.datetime | None = None) -> list[str]:
    """The HS256 keys a token may verify against, in order: the current key,
    then the previous key while its UNTIL is still in the future. Empty
    values are dropped, so an empty string is never tried as a key."""
    keys = [JWT_SECRET] if JWT_SECRET else []
    previous = (JWT_SECRET_PREVIOUS or "").strip()
    until = _previous_key_until(JWT_SECRET_PREVIOUS_UNTIL)
    if previous and until is not None and previous not in keys:
        now = now or datetime.datetime.now(datetime.timezone.utc)
        if now < until:
            keys.append(previous)
    return keys


def _migration_aware_claims_kwargs(token: str) -> dict[str, Any]:
    """Which of audience=/issuer= to pass to the real, signature-verified
    jwt.decode() call below, decided from the token's own *unverified*
    payload -- only used to decide whether to ask PyJWT to enforce a claim
    that's actually there, never to trust the claim's value itself (the
    verified decode call re-checks the value against the signed payload
    regardless). A token that predates PR12 (or a synthetic test token)
    has neither claim, so neither kwarg is passed for it -- same
    opportunistic, only-enforced-when-present approach
    omnibioai-auth/app/core/jwt.py::decode_token and omnibioai-iam-client's
    AsyncIAMClient use.
    """
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
    except Exception:
        return {}

    kwargs: dict[str, Any] = {}
    if "aud" in unverified:
        kwargs["audience"] = JWT_AUDIENCE
    if "iss" in unverified:
        kwargs["issuer"] = JWT_ISSUER
    return kwargs


def _decode(token: str) -> dict[str, Any]:
    """Verifies signature + expiry, dispatched by the token's own `alg`
    header rather than by any local config -- mirrors omnibioai-auth's own
    decode_token(). Every exit that doesn't return a signature-verified
    payload raises TokenInvalid: unknown/missing alg, unresolvable kid,
    unreachable JWKS endpoint, and bad signature all fail closed. There is
    no path that returns a payload without a verified signature."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as e:
        raise TokenInvalid(f"invalid token: {e}")

    alg = header.get("alg")
    claims_kwargs = _migration_aware_claims_kwargs(token)

    if alg == "RS256":
        kid = header.get("kid")
        if not kid:
            raise TokenInvalid("RS256 token missing kid header")
        try:
            signing_key = _get_jwks_client().get_signing_key(kid).key
        except PyJWKClientError as e:
            raise TokenInvalid(f"unable to resolve signing key: {e}")
        except Exception as e:
            # Covers JWKS-endpoint timeouts/connection errors and any
            # other fetch failure -- fail closed rather than falling back
            # to an unverified path.
            raise TokenInvalid(f"jwks fetch failed: {e}")
        try:
            return jwt.decode(token, signing_key, algorithms=["RS256"], **claims_kwargs)
        except jwt.ExpiredSignatureError:
            raise TokenInvalid("expired")
        except jwt.InvalidTokenError as e:
            raise TokenInvalid(f"invalid token: {e}")

    if alg == "HS256":
        # Only a signature mismatch moves on to the next key. PyJWT checks
        # the signature before exp/aud/iss, so any other error means this
        # key verified the signature and the token itself is unacceptable.
        keys = _hs256_keys()
        if not keys:
            raise TokenInvalid("no HS256 verification key configured")
        for key in keys:
            try:
                return jwt.decode(token, key, algorithms=["HS256"], **claims_kwargs)
            except jwt.InvalidSignatureError:
                continue
            except jwt.ExpiredSignatureError:
                raise TokenInvalid("expired")
            except jwt.InvalidTokenError as e:
                raise TokenInvalid(f"invalid token: {e}")
        raise TokenInvalid("invalid token: Signature verification failed")

    raise TokenInvalid(f"unsupported alg: {alg!r}")


def verify_token(token: str | None) -> dict[str, Any]:
    """Decodes and verifies `token`. Returns the decoded payload on
    success; raises TokenInvalid on any failure."""
    if not token:
        raise TokenInvalid("missing token")

    payload = _decode(token)

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
            # Revocation state is part of the authorization decision. An
            # unavailable or authentication-rejected Redis must not be
            # treated as an empty blacklist.
            raise TokenInvalid("revocation state unavailable")
        if revoked:
            raise TokenInvalid("revoked")

    return payload
