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


def _patch_all(*, org=None, members=None, login_success=None, login_failure=None, org_events=None, rag_events=None,
                trunc_success=False, trunc_failure=False, trunc_org=False, trunc_rag=False):
    return [
        patch("control_center.compliance.service.auth_client.get_organization", AsyncMock(return_value=org)),
        patch("control_center.compliance.service.auth_client.get_org_members", AsyncMock(return_value=members or [])),
        patch(
            "control_center.compliance.service.auth_client.list_all_audit_events",
            AsyncMock(side_effect=[
                (login_success or [], trunc_success),
                (login_failure or [], trunc_failure),
                (org_events or [], trunc_org),
            ]),
        ),
        patch("control_center.compliance.service.billing_client.list_all_usage_events", AsyncMock(return_value=(rag_events or [], trunc_rag))),
    ]


class BuildReportTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_basic_shape_and_organization_name(self) -> None:
        patches = _patch_all(org={"id": 1, "name": "KUMC Research"}, members=_MEMBERS)
        for p in patches:
            p.start()
        try:
            report = await service.build_report(
                organization_id=1, from_date=date(2026, 8, 1), to_date=date(2026, 8, 31),
                generated_by="admin@omnibioai.org", authorization="Bearer tok",
            )
        finally:
            for p in patches:
                p.stop()

        self.assertEqual(report["organization_name"], "KUMC Research")
        self.assertEqual(report["organization_id"], 1)
        self.assertEqual(report["summary"]["total_users"], 2)
        self.assertEqual(report["generated_by"], "admin@omnibioai.org")

    async def test_organization_name_falls_back_when_org_lookup_fails(self) -> None:
        patches = _patch_all(org=None, members=_MEMBERS)
        for p in patches:
            p.start()
        try:
            report = await service.build_report(
                organization_id=9, from_date=date(2026, 8, 1), to_date=date(2026, 8, 31),
                generated_by="admin@omnibioai.org", authorization="Bearer tok",
            )
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(report["organization_name"], "Organization #9")

    async def test_login_events_filtered_to_org_members_only(self) -> None:
        login_success = [
            {"actor_user_id": 1, "actor_email": None, "metadata": {"email": "alice@kumc.edu"}, "created_at": "2026-08-05T10:00:00"},
            {"actor_user_id": None, "actor_email": None, "metadata": {"email": "outsider@other.org"}, "created_at": "2026-08-05T11:00:00"},
        ]
        patches = _patch_all(org={"name": "KUMC"}, members=_MEMBERS, login_success=login_success)
        for p in patches:
            p.start()
        try:
            report = await service.build_report(
                organization_id=1, from_date=date(2026, 8, 1), to_date=date(2026, 8, 31),
                generated_by="admin@omnibioai.org", authorization="Bearer tok",
            )
        finally:
            for p in patches:
                p.stop()

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
        patches = _patch_all(org={"name": "KUMC"}, members=_MEMBERS, login_success=login_success, login_failure=login_failure)
        for p in patches:
            p.start()
        try:
            report = await service.build_report(
                organization_id=1, from_date=date(2026, 8, 1), to_date=date(2026, 8, 31),
                generated_by="admin@omnibioai.org", authorization="Bearer tok",
            )
        finally:
            for p in patches:
                p.stop()

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
        patches = _patch_all(org={"name": "KUMC"}, members=_MEMBERS, rag_events=rag_events)
        for p in patches:
            p.start()
        try:
            report = await service.build_report(
                organization_id=1, from_date=date(2026, 8, 1), to_date=date(2026, 8, 31),
                generated_by="admin@omnibioai.org", authorization="Bearer tok",
            )
        finally:
            for p in patches:
                p.stop()

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
        patches = _patch_all(org={"name": "KUMC"}, members=_MEMBERS, org_events=org_events)
        for p in patches:
            p.start()
        try:
            report = await service.build_report(
                organization_id=1, from_date=date(2026, 8, 1), to_date=date(2026, 8, 31),
                generated_by="admin@omnibioai.org", authorization="Bearer tok",
            )
        finally:
            for p in patches:
                p.stop()

        by_type = {r["event_type"]: r for r in report["security_events"]}
        self.assertEqual(by_type["role_assigned"]["outcome"], "success")
        self.assertEqual(by_type["role_assignment_denied"]["outcome"], "deny")
        self.assertEqual(by_type["sso_configuration_updated"]["actor_label"], "system")
        self.assertNotIn("some_unrelated_type", by_type)
        self.assertEqual(report["summary"]["security_incidents"], 1)  # role_assignment_denied only

    async def test_login_failures_appear_in_security_events(self) -> None:
        login_failure = [
            {"actor_user_id": 1, "actor_email": None, "metadata": {"email": "alice@kumc.edu"}, "created_at": "2026-08-06T10:00:00"},
        ]
        patches = _patch_all(org={"name": "KUMC"}, members=_MEMBERS, login_failure=login_failure)
        for p in patches:
            p.start()
        try:
            report = await service.build_report(
                organization_id=1, from_date=date(2026, 8, 1), to_date=date(2026, 8, 31),
                generated_by="admin@omnibioai.org", authorization="Bearer tok",
            )
        finally:
            for p in patches:
                p.stop()

        failed_login_rows = [r for r in report["security_events"] if r["event_type"] == "login_failure"]
        self.assertEqual(len(failed_login_rows), 1)
        self.assertEqual(failed_login_rows[0]["outcome"], "failure")
        self.assertEqual(report["summary"]["security_incidents"], 1)

    async def test_truncated_flag_propagates_from_any_source(self) -> None:
        patches = _patch_all(org={"name": "KUMC"}, members=_MEMBERS, trunc_rag=True)
        for p in patches:
            p.start()
        try:
            report = await service.build_report(
                organization_id=1, from_date=date(2026, 8, 1), to_date=date(2026, 8, 31),
                generated_by="admin@omnibioai.org", authorization="Bearer tok",
            )
        finally:
            for p in patches:
                p.stop()
        self.assertTrue(report["truncated"])

    async def test_no_activity_returns_empty_sections(self) -> None:
        patches = _patch_all(org={"name": "KUMC"}, members=_MEMBERS)
        for p in patches:
            p.start()
        try:
            report = await service.build_report(
                organization_id=1, from_date=date(2026, 8, 1), to_date=date(2026, 8, 31),
                generated_by="admin@omnibioai.org", authorization="Bearer tok",
            )
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(report["user_access"], [])
        self.assertEqual(report["rag_queries"], [])
        self.assertEqual(report["security_events"], [])
        self.assertEqual(report["summary"]["security_incidents"], 0)


if __name__ == "__main__":
    unittest.main()
