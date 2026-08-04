from __future__ import annotations

from fastapi import Header, HTTPException

from control_center.core.jwt_verify import TokenInvalid, verify_token


def require_permission(permission: str):
    """FastAPI dependency factory: 401 on missing/invalid/expired/revoked
    token, 403 if the token is valid but its `permissions` claim doesn't
    include `permission`. Returns a dependency that resolves to the
    decoded payload.

    Signature/expiry/type/required-claims/revocation checking is delegated
    to core.jwt_verify.verify_token (SSO Phase 2 PR3) -- unchanged by this
    function, which only owns the Authorization-header parsing and the
    authorization decision itself.

    PR3D: replaces the former require_admin's hardcoded `"admin" in roles`
    check. Authorization now reads the same `permissions` claim
    omnibioai-auth's own require_permission checks (app/rbac.py), against
    whatever permission string a given route needs -- e.g.
    "platform.manage_infra" -- rather than one blanket role flag every
    admin-gated route shared. Deliberately still a *global* permission
    check (payload["permissions"], not an org-scoped one): every route
    this dependency guards today is a platform-wide operational surface
    (docker/cron/known-issues/...), not a resource scoped to one
    organization, so it has no reason to assume -- and does not assume --
    that a user belongs to exactly one organization. A future org-scoped
    permission (e.g. "workflow.execute") is a separate, not-yet-needed
    concern this function's `permission: str` parameter already
    accommodates without modification; only the claim it's checked against
    would differ.
    """

    def _require_permission(authorization: str | None = Header(default=None)) -> dict:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "Missing or malformed Authorization header")

        token = authorization.split(" ", 1)[1].strip()
        try:
            payload = verify_token(token)
        except TokenInvalid as e:
            raise HTTPException(401, str(e))

        if permission not in (payload.get("permissions") or []):
            raise HTTPException(403, "Insufficient permissions")

        return payload

    return _require_permission
