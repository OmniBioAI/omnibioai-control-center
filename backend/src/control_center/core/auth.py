from __future__ import annotations

from fastapi import Header, HTTPException

from control_center.core.jwt_verify import TokenInvalid, verify_token


def require_admin(authorization: str | None = Header(default=None)) -> dict:
    """FastAPI dependency: 401 on missing/invalid/expired/revoked token, 403
    if the token is valid but lacks the "admin" role. Returns the decoded
    payload.

    Signature/expiry/type/required-claims/revocation checking is delegated
    to core.jwt_verify.verify_token (SSO Phase 2 PR3) -- this function only
    owns the Authorization-header parsing and the role-based authorization
    decision.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing or malformed Authorization header")

    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = verify_token(token)
    except TokenInvalid as e:
        raise HTTPException(401, str(e))

    if "admin" not in (payload.get("roles") or []):
        raise HTTPException(403, "Admin role required")

    return payload
