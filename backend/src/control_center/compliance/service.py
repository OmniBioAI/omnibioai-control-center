"""HIPAA Basic Compliance Report v0.8.0: data aggregation. Fans out to
omnibioai-auth (org roster + IAM audit ledger) and omnibioai-billing
(usage_events, Step 1's new read endpoint), then shapes the result into
the four sections this report actually has data for -- Executive Summary,
User Access Log, RAG Query Log, Security Events. No aggregation logic
lives in router.py (a later step): that file only owns request/response
wiring and the Redis cache-through, the same split analytics/router.py
already established for this codebase's other report-shaped endpoint
family.

Two real, source-level scoping gaps discovered while building this
(neither obvious from the task brief, both confirmed by reading the
producing code directly, not assumed):

1. login_success/login_failure AuditEvent rows in omnibioai-auth are
   NEVER organization-scoped (`app/services/auth_service.py`'s
   `authenticate_user`/`_log_login_failure` never pass `organization_id`
   to `audit_service.log_event` -- login happens before any org context
   is resolved). Filtering by organization_id would silently return zero
   rows for every org; not filtering would leak every other org's login
   activity into a report scoped to one org. Resolved here by fetching
   login events platform-wide, then filtering to this org's own roster
   (`auth_client.get_org_members`) client-side -- accurate for a user
   whose org membership hasn't changed near the report boundary; a user
   who joined/left around the edges of the requested period can be
   mis-included/excluded, since the roster is fetched as of "now", not
   as of the report period. This is a real, documented limitation (not
   fixed here -- it needs the org-scoped login architecture v0.9 is
   scoped to deliver), see test_multi_org_user_login_appears_in_every_
   member_org's_report in test_compliance_service.py for what this looks
   like in practice.
2. The generic cross-service audit ledger (omnibioai-security-audit's
   `audit_events` table, `decision=="deny"` for 403s) has no
   `organization_id` column at all (confirmed reading
   omnibioai-security-audit/db/models.py directly, and already known from
   Usage Analytics v1's own discovery -- see
   project_usage_analytics_v1 in memory). Deliberately NOT used as a
   Section 4 source for that reason -- including it would either be
   platform-wide data mislabeled as one org's, or silently empty if
   filtered. `role_assignment_denied` (omnibioai-auth's own IAM ledger,
   which IS organization_id-scoped -- verified in role_service.py) is
   the only per-org-accurate "access denied" signal available today, so
   Section 4's "permission denied" row reflects that specifically, not a
   generic 403 count.

Pre-merge security review fixes (2026-08-12):

- `sources_unavailable`: every auth_client/billing_client call now
  reports whether it actually succeeded, not just how much data it
  returned. A downstream outage is recorded by name in
  `sources_unavailable` rather than silently rendering as "this org had
  zero users/events" -- see auth_client.py's own docstring for the
  status vocabulary this consumes.
- `OrganizationNotFoundError`: get_organization's "not_found" status
  (a real 404 from omnibioai-auth, not a network failure) now raises
  here instead of silently falling back to a placeholder label --
  router.py converts this to a real HTTP 404.
- generated_by/generated_at are NO LONGER part of this function's
  return value or the cached payload -- router.py stamps them fresh on
  every response, cached or not, so a cache hit can never attribute the
  report to whichever admin happened to trigger the original cache-miss
  computation. See router.py's own comment at the call site.
- `security_incidents` (a name implying a legal/HIPAA reportable
  determination this report never makes) is replaced by two separate,
  more honestly-named counters: `failed_login_attempts` (routine,
  expected operational noise) and `security_events_requiring_review`
  (role_assignment_denied/mfa_verification_failed specifically -- see
  _INCIDENT_EVENT_TYPES). The Section 4 events table itself is
  unchanged -- both kinds of event still appear there, only the Section
  1 summary terminology changed.
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Optional

from control_center.compliance import auth_client, billing_client

# omnibioai-auth/app/services/audit_service.py::AuditEventType -- the
# subset that belongs in Section 4 (Security Events). login_success/
# login_failure are handled separately (Section 2 + the "failed
# authentications" row) since they need the org-membership filter above;
# every event_type here IS organization_id-scoped at the source, so
# org_scoped_events (fetched with organization_id=org_id already applied)
# needs no further filtering.
_SECURITY_EVENT_TYPES = {
    "role_created", "role_assigned", "role_removed",
    "permission_granted", "permission_revoked",
    "organization_membership_changed",
    "role_assignment_denied",
    "user_enabled", "user_disabled",
    "api_key_created", "api_key_revoked",
    "oauth_client_created", "oauth_client_revoked",
    "sso_configuration_created", "sso_configuration_updated", "sso_enforcement_changed",
    "sso_override_created", "sso_override_removed",
    "mfa_reset_by_admin", "mfa_verification_failed",
}

# Event types whose mere occurrence belongs in Section 1's
# security_events_requiring_review count -- denials/failures, not every
# role change (an admin routinely assigning a role isn't something that
# needs review; a rejected privilege-escalation attempt or a failed MFA
# check is). Deliberately excludes login_failure -- that has its own,
# separately-named counter (failed_login_attempts) precisely because a
# mistyped password is not the same kind of thing as a rejected
# escalation attempt, and conflating them under one "incidents" number
# was the exact problem this rename fixes.
_INCIDENT_EVENT_TYPES = {"role_assignment_denied", "mfa_verification_failed"}


class OrganizationNotFoundError(Exception):
    """Raised when omnibioai-auth confirms (a real 404, not a network
    failure -- see auth_client.get_organization's own docstring) that
    `organization_id` doesn't exist. router.py converts this to an HTTP
    404; every other failure mode degrades to a "some data unavailable"
    warning instead, since this is the one case where the report itself
    cannot mean anything at all."""

    def __init__(self, organization_id: int):
        super().__init__(f"Organization {organization_id} not found")
        self.organization_id = organization_id


def _humanize_event_type(event_type: str) -> str:
    return event_type.replace("_", " ").title()


def _is_org_member(event: dict, member_by_id: dict, member_by_email: dict) -> bool:
    actor_user_id = event.get("actor_user_id")
    if actor_user_id is not None and actor_user_id in member_by_id:
        return True
    email = (event.get("metadata") or {}).get("email")
    return email is not None and email in member_by_email


def _build_user_access(login_success: list[dict], login_failure: list[dict]) -> list[dict]:
    """One row per org member with any login activity in the period --
    login_count/last_login from login_success, failed_attempts from
    login_failure, grouped by email (metadata.email is always set on both
    event kinds -- see auth_service.py's own log_event calls -- unlike
    actor_email, which is None for an unknown-account failed attempt)."""
    rows: dict[str, dict[str, Any]] = {}

    for event in login_success:
        email = (event.get("metadata") or {}).get("email") or event.get("actor_email") or "unknown"
        row = rows.setdefault(email, {"user_label": email, "login_count": 0, "last_login": None, "failed_attempts": 0})
        row["login_count"] += 1
        created_at = event.get("created_at")
        if row["last_login"] is None or (created_at and created_at > row["last_login"]):
            row["last_login"] = created_at

    for event in login_failure:
        email = (event.get("metadata") or {}).get("email") or event.get("actor_email") or "unknown"
        row = rows.setdefault(email, {"user_label": email, "login_count": 0, "last_login": None, "failed_attempts": 0})
        row["failed_attempts"] += 1

    return sorted(rows.values(), key=lambda r: r["user_label"])


def _build_rag_queries(usage_events: list[dict], member_by_id: dict) -> list[dict]:
    rows = []
    for event in usage_events:
        user_id = event.get("user_id")
        member = member_by_id.get(int(user_id)) if user_id and user_id.isdigit() else None
        rows.append({
            "timestamp": event.get("timestamp"),
            "user_label": member["email"] if member else (user_id or "unknown"),
            "trace_id": event.get("trace_id"),
        })
    rows.sort(key=lambda r: r["timestamp"] or "", reverse=True)
    return rows


def _build_security_events(org_login_failure: list[dict], org_scoped_events: list[dict]) -> list[dict]:
    rows = []
    for event in org_login_failure:
        email = (event.get("metadata") or {}).get("email") or event.get("actor_email") or "unknown"
        rows.append({
            "timestamp": event.get("created_at"),
            "label": "Failed Login",
            "actor_label": email,
            "outcome": "failure",
            "event_type": "login_failure",
        })
    for event in org_scoped_events:
        event_type = event.get("event_type")
        if event_type not in _SECURITY_EVENT_TYPES:
            continue
        actor_label = event.get("actor_email") or (
            f"User #{event['actor_user_id']}" if event.get("actor_user_id") is not None else "system"
        )
        outcome = "deny" if event_type in _INCIDENT_EVENT_TYPES else "success"
        rows.append({
            "timestamp": event.get("created_at"),
            "label": _humanize_event_type(event_type),
            "actor_label": actor_label,
            "outcome": outcome,
            "event_type": event_type,
        })
    rows.sort(key=lambda r: r["timestamp"] or "", reverse=True)
    return rows


async def build_report(
    *,
    organization_id: int,
    from_date: date,
    to_date: date,
    authorization: Optional[str],
) -> dict[str, Any]:
    """Returns the cacheable report body -- everything EXCEPT
    generated_by/generated_at, which router.py stamps fresh on every
    response (cached or not) so a cache hit is never attributed to the
    wrong administrator. See this module's own docstring, "Pre-merge
    security review fixes", for why that split exists.
    """
    start_dt = datetime.combine(from_date, time.min)
    end_dt = datetime.combine(to_date, time.max)

    org, org_status = await auth_client.get_organization(organization_id, authorization)
    if org_status == "not_found":
        raise OrganizationNotFoundError(organization_id)

    members, members_status = await auth_client.get_org_members(organization_id, authorization)
    member_by_id = {m["user_id"]: m for m in members}
    member_by_email = {m["email"]: m for m in members}

    login_success_events, trunc_success, unavail_success = await auth_client.list_all_audit_events(
        organization_id=None, start_date=start_dt, end_date=end_dt,
        event_type="login_success", authorization=authorization,
    )
    login_failure_events, trunc_failure, unavail_failure = await auth_client.list_all_audit_events(
        organization_id=None, start_date=start_dt, end_date=end_dt,
        event_type="login_failure", authorization=authorization,
    )
    org_scoped_events, trunc_org, unavail_org = await auth_client.list_all_audit_events(
        organization_id=organization_id, start_date=start_dt, end_date=end_dt,
        authorization=authorization,
    )
    rag_events, trunc_rag, unavail_rag = await billing_client.list_all_usage_events(
        organization_id=organization_id, start_date=from_date, end_date=to_date,
        resource="rag.query", authorization=authorization,
    )

    # Human-readable, self-contained strings -- these are consumed
    # as-is by the JSON response, the PDF template, and the CSV export,
    # so the label is decided exactly once, here, rather than needing an
    # internal-key-to-label mapping duplicated in three render layers.
    sources_unavailable: list[str] = []
    if org_status == "unavailable":
        sources_unavailable.append("Organization details (omnibioai-auth)")
    if members_status != "ok":
        sources_unavailable.append("Organization members (omnibioai-auth)")
    if unavail_success:
        sources_unavailable.append("Login success events (omnibioai-auth)")
    if unavail_failure:
        sources_unavailable.append("Login failure events (omnibioai-auth)")
    if unavail_org:
        sources_unavailable.append("Role/permission/security events (omnibioai-auth)")
    if unavail_rag:
        sources_unavailable.append("RAG query events (omnibioai-billing)")

    org_login_success = [e for e in login_success_events if _is_org_member(e, member_by_id, member_by_email)]
    org_login_failure = [e for e in login_failure_events if _is_org_member(e, member_by_id, member_by_email)]

    user_access = _build_user_access(org_login_success, org_login_failure)
    rag_queries = _build_rag_queries(rag_events, member_by_id)
    security_events = _build_security_events(org_login_failure, org_scoped_events)

    security_events_requiring_review = sum(1 for r in security_events if r["outcome"] == "deny")

    summary = {
        "total_users": len(members),
        "active_users": sum(1 for r in user_access if r["login_count"] > 0),
        "total_rag_queries": len(rag_queries),
        "failed_login_attempts": len(org_login_failure),
        "security_events_requiring_review": security_events_requiring_review,
    }

    return {
        "organization_id": organization_id,
        "organization_name": (org or {}).get("name") or f"Organization #{organization_id}",
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "summary": summary,
        "user_access": user_access,
        "rag_queries": rag_queries,
        "security_events": security_events,
        "truncated": trunc_success or trunc_failure or trunc_org or trunc_rag,
        "sources_unavailable": sources_unavailable,
    }
