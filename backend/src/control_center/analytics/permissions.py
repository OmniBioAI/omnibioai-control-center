"""Multi-tenant RBAC for /analytics/* (task brief Section 8). Every
decision comes from the already-verified JWT payload
(`core.jwt_verify.verify_token`) -- the same trust model
`core/auth.py::require_permission` already uses for global permissions,
extended here to the `org_id`/`org_role`/`team_id`/`team_role` claims
omnibioai-auth's own `build_user_claims` (Phase 1 PR3, Team Management
v0.8.0 Step 3) already puts on every access token. No new remote
authorization call per request -- reusing the existing IAM/JWT system,
not building a second one, per the task brief's explicit instruction.

A caller-supplied `org_id`/`team_id` query parameter is always validated
against these claims, never trusted as-is (task brief: "Never trust a
client-provided org_id without validating it against the authenticated
user's permissions").
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException, Query

from control_center.core.jwt_verify import TokenInvalid, verify_token

# The real permission/role names, not invented ones:
# - MANAGE_ALL_ORGS: omnibioai-auth/app/rbac.py's own platform-admin
#   bypass permission.
# - ORG_ADMIN_ROLE: omnibioai-auth/app/services/org_service.py::
#   ORG_ADMIN_ROLE, the actual Role.name a token's org_role list contains.
# - TEAM_ADMIN_ROLE: the TeamMember.role value ("admin") Team Management
#   v0.8.0's own team_role claim carries for a team's admin.
MANAGE_ALL_ORGS = "manage_all_orgs"
ORG_ADMIN_ROLE = "org_admin"
TEAM_ADMIN_ROLE = "admin"


@dataclass(frozen=True)
class AnalyticsScope:
    """The resolved scope a caller may see -- every downstream function
    (aggregator reads, billing/TES calls) takes this, never the raw JWT
    payload, so there is exactly one place the org_id/team_id a request
    is allowed to see is decided.

    `org_id=None` means "platform-wide" -- only ever true for a
    platform_admin who didn't pass an org_id query param. Every other
    caller always resolves to a concrete org_id (their own).
    """

    is_platform_admin: bool
    org_id: Optional[int]
    team_id: Optional[int]
    user_id: Optional[str]


def _decode(authorization: Optional[str]) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing or malformed Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    try:
        return verify_token(token)
    except TokenInvalid as e:
        raise HTTPException(401, str(e))


def require_analytics_scope(
    authorization: Optional[str] = Header(default=None),
    org_id: Optional[int] = Query(default=None),
    team_id: Optional[int] = Query(default=None),
) -> AnalyticsScope:
    """FastAPI dependency: 401 on a missing/invalid/expired/revoked
    token, 403 on a valid token that doesn't grant analytics access at
    all, or that requests an org_id/team_id outside what it's entitled
    to. Returns the resolved `AnalyticsScope`.

    - platform_admin (`manage_all_orgs` permission): any org_id/team_id
      query param is honored as-is; omitting org_id resolves to
      platform-wide (`org_id=None`).
    - org_admin (`org_role` contains "org_admin"): always resolves to
      their own token org_id, regardless of what's asked for; a
      different org_id query param is 403. A team_id, if given, is
      passed through as-is -- an org_admin already has visibility into
      every team in their own org, so no further check is needed here.
    - team_admin (`team_role == "admin"`): always resolves to their own
      token org_id AND team_id; a different org_id or team_id query
      param is 403.
    - everyone else (no matching role): 403 -- regular users are denied
      analytics access entirely, per the task brief.
    """
    payload = _decode(authorization)

    permissions = payload.get("permissions") or []
    token_org_id = payload.get("org_id")
    token_org_role = payload.get("org_role") or []
    token_team_id = payload.get("team_id")
    token_team_role = payload.get("team_role")
    user_id = payload.get("sub")

    if MANAGE_ALL_ORGS in permissions:
        return AnalyticsScope(is_platform_admin=True, org_id=org_id, team_id=team_id, user_id=user_id)

    if ORG_ADMIN_ROLE in token_org_role and token_org_id is not None:
        if org_id is not None and org_id != token_org_id:
            raise HTTPException(403, "Forbidden: cannot access another organization's analytics")
        return AnalyticsScope(is_platform_admin=False, org_id=token_org_id, team_id=team_id, user_id=user_id)

    if token_team_role == TEAM_ADMIN_ROLE and token_team_id is not None and token_org_id is not None:
        if org_id is not None and org_id != token_org_id:
            raise HTTPException(403, "Forbidden: cannot access another organization's analytics")
        if team_id is not None and team_id != token_team_id:
            raise HTTPException(403, "Forbidden: cannot access another team's analytics")
        return AnalyticsScope(is_platform_admin=False, org_id=token_org_id, team_id=token_team_id, user_id=user_id)

    raise HTTPException(403, "Forbidden: analytics access requires an admin role")
