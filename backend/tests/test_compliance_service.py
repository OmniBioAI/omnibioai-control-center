"""Unit tests for control_center.compliance.service.build_report --
auth_client/billing_client are patched out entirely (their own httpx
behavior is covered by test_compliance_auth_client.py/
test_compliance_billing_client.py); this file only proves the
aggregation/shaping logic on top of them.
"""
from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from control_center.compliance import service

_MEMBERS = [
    {"user_id": 1, "email": "alice@kumc.edu", "status": "active", "roles": ["member"]},
    {"user_id": 2, "email": "bob@kumc.edu", "status": "active", "roles": ["org_admin"]},
]


def _patch_all(
    *, org=None, org_status="ok", members=None, members_status="ok",
    login_success=None, login_failure=None, org_events=None, rag_events=None,
    trunc_success=False, trunc_failure=False, trunc_org=False, trunc_rag=False,
    unavail_success=False, unavail_failure=False, unavail_org=False, unavail_rag=False,
):
    return [
        patch("control_center.compliance.service.auth_client.get_organization", AsyncMock(return_value=(org, org_status))),
        patch("control_center.compliance.service.auth_client.get_org_members", AsyncMock(return_value=(members or [], members_status))),
        patch(
            "control_center.compliance.service.auth_client.list_all_audit_events",
            AsyncMock(side_effect=[
                (login_success or [], trunc_success, unavail_success),
                (login_failure or [], trunc_failure, unavail_failure),
                (org_events or [], trunc_org, unavail_org),
            ]),
        ),
        patch(
            "control_center.compliance.service.billing_client.list_all_usage_events",
            AsyncMock(return_value=(rag_events or [], trunc_rag, unavail_rag)),
        ),
    ]


class BuildReportTestCase(unittest.IsolatedAsyncioTestCase):
    async def _build(self, patches, **kwargs) -> dict:
        for p in patches:
            p.start()
        try:
            return await service.build_report(
                organization_id=kwargs.pop("organization_id", 1),
                from_date=kwargs.pop("from_date", date(2026, 8, 1)),
                to_date=kwargs.pop("to_date", date(2026, 8, 31)),
                authorization=kwargs.pop("authorization", "Bearer tok"),
            )
        finally:
            for p in patches:
                p.stop()

    async def test_basic_shape_and_organization_name(self) -> None:
        report = await self._build(_patch_all(org={"id": 1, "name": "KUMC Research"}, members=_MEMBERS))
        self.assertEqual(report["organization_name"], "KUMC Research")
        self.assertEqual(report["organization_id"], 1)
        self.assertEqual(report["summary"]["total_users"], 2)
        # generated_by/generated_at are deliberately NOT part of this
        # function's return value -- router.py stamps them fresh per
        # request. See service.py's own module docstring.
        self.assertNotIn("generated_by", report)
        self.assertNotIn("generated_at", report)

    async def test_organization_name_falls_back_when_org_unavailable(self) -> None:
        report = await self._build(_patch_all(org=None, org_status="unavailable", members=_MEMBERS))
        self.assertEqual(report["organization_name"], "Organization #1")
        self.assertIn("Organization details (omnibioai-auth)", report["sources_unavailable"])

    async def test_nonexistent_organization_raises_not_found(self) -> None:
        patches = _patch_all(org=None, org_status="not_found", members=[])
        for p in patches:
            p.start()
        try:
            with self.assertRaises(service.OrganizationNotFoundError) as ctx:
                await service.build_report(
                    organization_id=999, from_date=date(2026, 8, 1), to_date=date(2026, 8, 31), authorization="Bearer tok",
                )
            self.assertEqual(ctx.exception.organization_id, 999)
        finally:
            for p in patches:
                p.stop()

    async def test_login_events_filtered_to_org_members_only(self) -> None:
        login_success = [
            {"actor_user_id": 1, "actor_email": None, "metadata": {"email": "alice@kumc.edu"}, "created_at": "2026-08-05T10:00:00"},
            {"actor_user_id": None, "actor_email": None, "metadata": {"email": "outsider@other.org"}, "created_at": "2026-08-05T11:00:00"},
        ]
        report = await self._build(_patch_all(org={"name": "KUMC"}, members=_MEMBERS, login_success=login_success))
        labels = [r["user_label"] for r in report["user_access"]]
        self.assertIn("alice@kumc.edu", labels)
        self.assertNotIn("outsider@other.org", labels)

    async def test_user_access_aggregates_login_count_and_last_login(self) -> None:
        login_success = [
            {"actor_user_id": 1, "actor_email": None, "metadata": {"email": "alice@kumc.edu"}, "created_at": "2026-08-05T10:00:00"},
            {"actor_user_id": 1, "actor_email": None, "metadata": {"email": "alice@kumc.edu"}, "created_at": "2026-08-20T10:00:00"},
        ]
        login_failure = [
            {"actor_user_id": 1, "actor_email": None, "metadata": {"email": "alice@kumc.edu"}, "created_at": "2026-08-06T10:00:00"},
        ]
        report = await self._build(_patch_all(org={"name": "KUMC"}, members=_MEMBERS, login_success=login_success, login_failure=login_failure))
        alice = next(r for r in report["user_access"] if r["user_label"] == "alice@kumc.edu")
        self.assertEqual(alice["login_count"], 2)
        self.assertEqual(alice["failed_attempts"], 1)
        self.assertEqual(alice["last_login"], "2026-08-20T10:00:00")
        self.assertEqual(report["summary"]["active_users"], 1)

    async def test_rag_queries_resolve_user_id_to_member_email(self) -> None:
        rag_events = [
            {"timestamp": "2026-08-10T09:00:00", "user_id": "2", "trace_id": "trace-1"},
            {"timestamp": "2026-08-11T09:00:00", "user_id": "999", "trace_id": "trace-2"},
        ]
        report = await self._build(_patch_all(org={"name": "KUMC"}, members=_MEMBERS, rag_events=rag_events))
        by_trace = {r["trace_id"]: r["user_label"] for r in report["rag_queries"]}
        self.assertEqual(by_trace["trace-1"], "bob@kumc.edu")
        self.assertEqual(by_trace["trace-2"], "999")
        self.assertEqual(report["summary"]["total_rag_queries"], 2)

    async def test_security_events_classifies_denial_vs_ordinary_change(self) -> None:
        org_events = [
            {"event_type": "role_assigned", "actor_email": "bob@kumc.edu", "actor_user_id": 2, "created_at": "2026-08-12T10:00:00"},
            {"event_type": "role_assignment_denied", "actor_email": "bob@kumc.edu", "actor_user_id": 2, "created_at": "2026-08-13T10:00:00"},
            {"event_type": "sso_configuration_updated", "actor_email": None, "actor_user_id": None, "created_at": "2026-08-14T10:00:00"},
            # not in _SECURITY_EVENT_TYPES -- must be excluded
            {"event_type": "some_unrelated_type", "actor_email": "bob@kumc.edu", "actor_user_id": 2, "created_at": "2026-08-15T10:00:00"},
        ]
        report = await self._build(_patch_all(org={"name": "KUMC"}, members=_MEMBERS, org_events=org_events))
        by_type = {r["event_type"]: r for r in report["security_events"]}
        self.assertEqual(by_type["role_assigned"]["outcome"], "success")
        self.assertEqual(by_type["role_assignment_denied"]["outcome"], "deny")
        self.assertEqual(by_type["sso_configuration_updated"]["actor_label"], "system")
        self.assertNotIn("some_unrelated_type", by_type)
        # Pre-merge review fix: security_incidents renamed/split. Only
        # the deny-classified event counts toward
        # security_events_requiring_review; no login failures here, so
        # failed_login_attempts is 0.
        self.assertEqual(report["summary"]["security_events_requiring_review"], 1)
        self.assertEqual(report["summary"]["failed_login_attempts"], 0)

    async def test_login_failures_appear_in_security_events_but_count_separately(self) -> None:
        login_failure = [
            {"actor_user_id": 1, "actor_email": None, "metadata": {"email": "alice@kumc.edu"}, "created_at": "2026-08-06T10:00:00"},
        ]
        report = await self._build(_patch_all(org={"name": "KUMC"}, members=_MEMBERS, login_failure=login_failure))
        failed_login_rows = [r for r in report["security_events"] if r["event_type"] == "login_failure"]
        self.assertEqual(len(failed_login_rows), 1)
        self.assertEqual(failed_login_rows[0]["outcome"], "failure")
        # Pre-merge review fix: a failed login is counted under
        # failed_login_attempts, NOT security_events_requiring_review --
        # conflating a mistyped password with a rejected escalation
        # attempt under one "incidents" number was the exact defect this
        # rename/split fixes.
        self.assertEqual(report["summary"]["failed_login_attempts"], 1)
        self.assertEqual(report["summary"]["security_events_requiring_review"], 0)

    async def test_truncated_flag_propagates_from_any_source(self) -> None:
        report = await self._build(_patch_all(org={"name": "KUMC"}, members=_MEMBERS, trunc_rag=True))
        self.assertTrue(report["truncated"])

    async def test_no_activity_returns_empty_sections(self) -> None:
        report = await self._build(_patch_all(org={"name": "KUMC"}, members=_MEMBERS))
        self.assertEqual(report["user_access"], [])
        self.assertEqual(report["rag_queries"], [])
        self.assertEqual(report["security_events"], [])
        self.assertEqual(report["summary"]["security_events_requiring_review"], 0)
        self.assertEqual(report["summary"]["failed_login_attempts"], 0)
        self.assertEqual(report["sources_unavailable"], [])

    # ── Pre-merge review fix: sources_unavailable ──────────────────────

    async def test_sources_unavailable_lists_every_failed_source_by_name(self) -> None:
        report = await self._build(_patch_all(
            org={"name": "KUMC"}, members=_MEMBERS,
            unavail_success=True, unavail_failure=True, unavail_org=True, unavail_rag=True,
        ))
        self.assertEqual(sorted(report["sources_unavailable"]), sorted([
            "Login success events (omnibioai-auth)",
            "Login failure events (omnibioai-auth)",
            "Role/permission/security events (omnibioai-auth)",
            "RAG query events (omnibioai-billing)",
        ]))

    async def test_members_unavailable_is_recorded_and_report_still_returns(self) -> None:
        report = await self._build(_patch_all(org={"name": "KUMC"}, members=[], members_status="unavailable"))
        self.assertIn("Organization members (omnibioai-auth)", report["sources_unavailable"])
        # Degrades gracefully -- does not raise, unlike the confirmed
        # not_found case.
        self.assertEqual(report["summary"]["total_users"], 0)

    async def test_partial_downstream_failure_does_not_silently_report_zero_everything(self) -> None:
        # RAG unavailable, but login data (a different, working source)
        # still came through -- the report must reflect BOTH: real login
        # activity AND an explicit warning that RAG data is missing, not
        # a blanket "everything is empty" that hides which part failed.
        login_success = [
            {"actor_user_id": 1, "actor_email": None, "metadata": {"email": "alice@kumc.edu"}, "created_at": "2026-08-05T10:00:00"},
        ]
        report = await self._build(_patch_all(org={"name": "KUMC"}, members=_MEMBERS, login_success=login_success, unavail_rag=True))
        self.assertEqual(report["summary"]["total_rag_queries"], 0)
        self.assertEqual(report["summary"]["active_users"], 1)
        self.assertEqual(report["sources_unavailable"], ["RAG query events (omnibioai-billing)"])

    # ── Pre-merge review fix: multi-org login attribution (documented,
    # not fixed -- v0.9 architecture work; this test locks in the
    # current, known-limitation behavior so a future change to it is a
    # deliberate decision, not an accidental regression). ─────────────

    async def test_multi_org_user_login_appears_in_every_member_org_report(self) -> None:
        shared_user_login = [
            {"actor_user_id": 1, "actor_email": None, "metadata": {"email": "alice@kumc.edu"}, "created_at": "2026-08-05T10:00:00"},
        ]
        org_a_members = [{"user_id": 1, "email": "alice@kumc.edu", "status": "active", "roles": ["member"]}]
        org_b_members = [{"user_id": 1, "email": "alice@kumc.edu", "status": "active", "roles": ["member"]}]

        report_a = await self._build(
            _patch_all(org={"name": "Org A"}, members=org_a_members, login_success=shared_user_login),
            organization_id=1,
        )
        report_b = await self._build(
            _patch_all(org={"name": "Org B"}, members=org_b_members, login_success=shared_user_login),
            organization_id=2,
        )

        # Same underlying login event, attributed to BOTH organizations'
        # reports -- login events carry no organization_id at the
        # source (see service.py's own module docstring, gap #1), so a
        # user who is a member of two orgs cannot be disambiguated
        # further today.
        self.assertEqual([r["user_label"] for r in report_a["user_access"]], ["alice@kumc.edu"])
        self.assertEqual([r["user_label"] for r in report_b["user_access"]], ["alice@kumc.edu"])


if __name__ == "__main__":
    unittest.main()
